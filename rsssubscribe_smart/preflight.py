"""Pure, fail-closed torrent preflight helpers; no downloader mutation."""
from pathlib import Path
import re
VIDEO = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.webm', '.mpeg', '.mpg'}


def actual_episodes(files, season):
    episodes = set()
    for name in files:
        if Path(name).suffix.lower() not in VIDEO:
            continue
        # Only unambiguous single-episode files are safe for native selection.
        match = re.search(r'(?i)(?<![a-z0-9])S(\d{1,3})[ ._-]*E(\d{1,4})(?!\d)', Path(name).name)
        if not match or re.match(r'(?i)(?:[-_][ ._]*E?\d|[ .]*E\d)', Path(name).name[match.end():]):
            raise ValueError('种子视频文件季集映射不明确，延后处理')
        if int(match[1]) != season:
            raise ValueError('跨季种子，延后处理')
        episodes.add(int(match[2]))
    if not episodes:
        raise ValueError('种子没有可确认的剧集视频文件，延后处理')
    return episodes


def hash_exists(module, torrent_hash):
    servers = module.get_instances()
    if not servers:
        raise RuntimeError('没有可查询的下载器')
    for server in servers.values():
        result = server.get_torrents()
        if not result or result[0] is None or result[1]:
            raise RuntimeError('下载器查询失败，延后处理')
        if any(str(t.get('hash', '')).lower() == torrent_hash.lower() for t in result[0]):
            return True
    return False
