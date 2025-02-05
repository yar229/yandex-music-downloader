#!/bin/python3
import argparse
import datetime as dt
from datetime import datetime
import logging
import re
import sys
import tempfile
import time
import os
from pathlib import Path
from typing import Optional

from requests import Session
from requests_cache import CachedSession, FileCache

from ymd import core
from ymd.ym_api import BasicTrackInfo, PlaylistId, api

DEFAULT_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36'
DEFAULT_DELAY = 3

CACHE_EXPIRE_AFTER = dt.timedelta(hours=8)
CACHE_DIR = Path(tempfile.gettempdir()) / 'ymd'

TRACK_RE = re.compile(r'track/(\d+)$')
ALBUM_RE = re.compile(r'album/(\d+)$')
ARTIST_RE = re.compile(r'artist/(\d+)$')
PLAYLIST_RE = re.compile(r'([\w\-._]+)/playlists/(\d+)$')






def args_playlist_id(arg: str) -> api.PlaylistId:
    arr = arg.split('/')
    return PlaylistId(owner=arr[0], kind=int(arr[1]))


def help_str(text: Optional[str] = None) -> str:
    default = 'по умолчанию: %(default)s'
    if text is None:
        return default
    return f'{text} ({default})'


def main():
    parser = argparse.ArgumentParser(
        description='Загрузчик музыки с сервиса Яндекс.Музыка')

    common_group = parser.add_argument_group('Общие параметры')
    common_group.add_argument('--hq',
                              action='store_true',
                              help='Загружать треки в высоком качестве')
    common_group.add_argument('--skip-existing',
                              action='store_true',
                              help='Пропускать уже загруженные треки')
    common_group.add_argument('--add-lyrics',
                              action='store_true',
                              help='Загружать тексты песен')
    common_group.add_argument('--embed-cover',
                              action='store_true',
                              help='Встраивать обложку в .mp3 файл')
    common_group.add_argument('--cover-resolution',
                              default=core.DEFAULT_COVER_RESOLUTION,
                              metavar='<Разрешение обложки>',
                              type=int,
                              help=help_str(None))
    common_group.add_argument(
        '--delay',
        default=DEFAULT_DELAY,
        metavar='<Задержка>',
        type=int,
        help=help_str('Задержка между запросами, в секундах'))
    common_group.add_argument('--stick-to-artist',
                              action='store_true',
                              help='Загружать альбомы, созданные'
                              ' только данным исполнителем')
    common_group.add_argument('--only-music',
                              action='store_true',
                              help='Загружать только музыкальные альбомы'
                              ' (пропускать подкасты и аудиокниги)')
    common_group.add_argument('--enable-caching',
                              action='store_true',
                              help='Включить кэширование. Данная опция полезна'
                              ' при нестабильном интернете.'
                              f' (кэш хранится в папке {CACHE_DIR})')
    common_group.add_argument('--debug',
                              action='store_true',
                              help=argparse.SUPPRESS)

    common_group.add_argument('--logpath',
                            metavar='<Папка>',
                            help=help_str('Log files folder'),
                            type=Path)

    id_group_meta = parser.add_argument_group('ID')
    id_group = id_group_meta.add_mutually_exclusive_group(required=True)
    id_group.add_argument('--artist-id', metavar='<ID исполнителя>')
    id_group.add_argument('--album-id', metavar='<ID альбома>')
    id_group.add_argument('--track-id', metavar='<ID трека>')
    id_group.add_argument('--playlist-id',
                          type=args_playlist_id,
                          metavar='<владелец плейлиста>/<тип плейлиста>')
    id_group.add_argument('-u',
                          '--url',
                          help='URL исполнителя/альбома/трека/плейлиста')

    path_group = parser.add_argument_group('Указание пути')
    path_group.add_argument('--unsafe-path',
                            action='store_true',
                            help='Не очищать путь от недопустимых символов')
    path_group.add_argument('--dir',
                            default='.',
                            metavar='<Папка>',
                            help=help_str('Папка для загрузки музыки'),
                            type=Path)
    path_group.add_argument(
        '--path-pattern',
        default=core.DEFAULT_PATH_PATTERN,
        metavar='<Паттерн>',
        type=Path,
        help=help_str('Поддерживает следующие заполнители:'
                      ' #number, #artist, #album-artist, #title,'
                      ' #album, #year, #artist-id, #album-id, #track-id'))

    auth_group = parser.add_argument_group('Авторизация')
    auth_group.add_argument('--session-id',
                            required=True,
                            metavar='<ID сессии>')
    auth_group.add_argument('--spravka', metavar='<Spravka>')
    auth_group.add_argument('--user-agent',
                            default=DEFAULT_USER_AGENT,
                            metavar='<User-Agent>',
                            help=help_str())

    args = parser.parse_args()



    # Logging =============================================================================================================================
    _log_format = '%(asctime)s\t%(levelname)s\t%(message)s'
    logging.basicConfig(
        datefmt = '%H:%M:%S',
        format = _log_format,
        level = logging.DEBUG if args.debug else logging.INFO
    )
    _logger = logging.getLogger('yandex-music-downloader')

    #stream_handler = logging.StreamHandler()
    #_logger.addHandler(stream_handler)
    
    if (args.logpath is not None):
        file_handler = logging.FileHandler(os.path.join(args.logpath, f'yandex-music-downloader {datetime.now().strftime("%Y-%m-%d %H-%M-%S")}.log'), 'w', encoding = 'utf-8')
        file_handler.setFormatter(logging.Formatter(_log_format))
        file_handler.setLevel(logging.DEBUG if args.debug else logging.INFO)
        _logger.addHandler(file_handler)
    # End Logging =============================================================================================================================




    def response_hook(resp, **kwargs):
        del kwargs
        #if logger.isEnabledFor(logging.DEBUG):
        #    target_headers = ['application/json', 'text/xml']
        #    if any(h in resp.headers['Content-Type'] for h in target_headers):
        #        logger.debug(resp.text)
        if not resp.ok:
            _logger.error(f'Error code: {resp.status_code}')
            if resp.status_code == 400:
                _logger.error('Информация по устранению данной ошибки: https://github.com/llistochek/yandex-music-downloader#%D0%BE%D1%88%D0%B8%D0%B1%D0%BA%D0%B0-400')
            sys.exit(3)
        if not getattr(resp, 'from_cache', False):
            time.sleep(args.delay)

    def setup_session(session: Session):
        core.setup_session(session, args.session_id, args.user_agent,
                           args.spravka)
        session.hooks = {'response': response_hook}

    session = cached_session = Session()
    if args.enable_caching:
        cached_session = CachedSession(backend=FileCache(cache_name=CACHE_DIR),
                                       expire_after=CACHE_EXPIRE_AFTER)

    setup_session(session)
    setup_session(cached_session)

    result_tracks: list[BasicTrackInfo] = []

    if args.url is not None:
        if match := ARTIST_RE.search(args.url):
            args.artist_id = match.group(1)
        elif match := ALBUM_RE.search(args.url):
            args.album_id = match.group(1)
        elif match := TRACK_RE.search(args.url):
            args.track_id = match.group(1)
        elif match := PLAYLIST_RE.search(args.url):
            args.playlist_id = PlaylistId(owner=match.group(1),
                                          kind=int(match.group(2)))
        else:
            _logger.error('url parameter wrong format')
            return 1

    if args.artist_id is not None:
        artist_info = api.get_artist_info(cached_session, args.artist_id)
        albums_count = 0
        for album in artist_info.albums:
            if args.stick_to_artist and album.artists[0].name != artist_info.name:
                _logger.warning(f'Skipping album "{album.title}" cause of --stick-to-artist flag set')
                continue
            if args.only_music and album.meta_type != 'music':
                _logger.warning(f'Skipping non-musical album "{album.title}" ')
                continue
            full_album = api.get_full_album_info(cached_session, album.id)
            result_tracks.extend(full_album.tracks)
            albums_count += 1
        _logger.info(f'Artist: {artist_info.name}, albums: {albums_count}')
    elif args.album_id is not None:
        album = api.get_full_album_info(cached_session, args.album_id)
        _logger.info(f'Album: {album.title}')
        result_tracks = album.tracks
    elif args.track_id is not None:
        result_tracks = [
            api.get_full_track_info(cached_session, args.track_id)
        ]
    elif args.playlist_id is not None:
        result_tracks = api.get_playlist(cached_session, args.playlist_id)

    _logger.info(f'Total tracks: {len(result_tracks)}')

    covers_cache: dict[str, bytes] = {}
    cnt = 0
    for track in result_tracks:
        save_path = args.dir / core.prepare_track_path(args.path_pattern,
                                                       track, args.unsafe_path)
        if args.skip_existing and save_path.is_file():
            continue

        save_dir = save_path.parent
        if not save_dir.is_dir():
            save_dir.mkdir(parents=True)

        _logger.info(f'Loading track: {save_path}')
         
        core.download_track(session=session,
                            track=track,
                            target_path=save_path,
                            hq=args.hq,
                            add_lyrics=args.add_lyrics,
                            embed_cover=args.embed_cover,
                            cover_resolution=args.cover_resolution,
                            covers_cache=covers_cache)
        cnt += 1

    _logger.info(f'Finished, tracks downloaded: {cnt}')