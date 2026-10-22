"""Local RSS pre-download guard. No torrent deletion; qBittorrent only.
Identity: media type + TMDB + exact season/episode. Unknown overlap defers.
"""
import contextlib
import fcntl
import json
import re
import time
from pathlib import Path

VIDEO = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.webm', '.mpeg', '.mpg'}
FAILED = {'error', 'missingFiles'}


def resolution(text):
    values = [int(x) for x in re.findall(r'(?i)(?<!\d)(4320|2160|1080|720|576|480|360)[pi](?!\d)', text or '')]
    if re.search(r'(?i)(?<![a-z0-9])4k(?![a-z0-9])', text or ''):
        values.append(2160)
    return max(values, default=0)


def blocks(candidate, existing):
    # Only the explicitly requested 1080p -> 2160p upgrade is automatic.
    # Unknown quality is not evidence that a new download is an upgrade.
    return not (candidate == 2160 and existing == 1080)


def has_chinese_subtitle(text):
    """Return whether title/description explicitly advertises Chinese subtitles."""
    return bool(re.search(
        r'(?i)(中字|简中|繁中|简繁|中文字幕|中文字幕|CHS|CHT|GB\b|BIG5\b|中文翻译|\bChinese(?:\.Sub|[ ._-]*Subtitle))',
        text or '',
    ))


def rule_matches(text, minimum_resolution=0, subtitle_mode='any'):
    """Apply a conservative RSS quality/subtitle rule to visible metadata."""
    current = resolution(text)
    if minimum_resolution and current < int(minimum_resolution):
        return False, f'分辨率 {current or "未知"} 低于要求 {minimum_resolution}'
    subtitle = has_chinese_subtitle(text)
    if subtitle_mode == 'required' and not subtitle:
        return False, '未标注中文字幕'
    if subtitle_mode == 'forbidden' and subtitle:
        return False, '标注了中文字幕'
    return True, ''


def identity(media):
    mid = getattr(media, 'tmdb_id', None)
    kind = getattr(getattr(media, 'type', None), 'value', None)
    return (kind, int(mid)) if mid and kind in {'电影', '电视剧'} else None


def explicit_pairs(text):
    """Only explicit single-season, single-episode video names are trusted."""
    matches = list(re.finditer(r'(?i)S(\d{1,3})[ ._-]*E(\d{1,4})(?!\d)', text))
    if len(matches) != 1:
        return None
    m = matches[0]
    if re.match(r'(?i)(?:[ ._-]*E\d|\s*-\s*(?:E)?\d)', text[m.end():]):
        return None
    return int(m[1]), int(m[2])


def selected_pairs(files):
    selected = [f for f in files if f.get('priority', 1) != 0 and Path(f['name']).suffix.lower() in VIDEO]
    if not selected:
        return None
    pairs = {explicit_pairs(Path(f['name']).name) for f in selected}
    return None if None in pairs else pairs


@contextlib.contextmanager
def exclusive(root, timeout=30):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'rss-download-dedupe.lock').open('a') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('RSS判重锁超时，本条延后处理')
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Guard:
    def __init__(self, root, module, history, logger, transferred=None):
        self.root = Path(root)
        self.module = module
        self.history = history
        self.logger = logger
        self.pending = self.root / 'rss-download-pending.json'
        self.transferred = transferred

    def decide(self, media, meta, existing):
        """Return (skip reason, selected missing episodes or None). Called locked."""
        ident = identity(media)
        if not ident:
            raise RuntimeError('媒体身份不明确，延后处理')
        tv = ident[0] == '电视剧'
        season = getattr(meta, 'begin_season', None)
        episodes = set(getattr(meta, 'episode_list', None) or [])
        seasons = set(getattr(meta, 'season_list', None) or [])
        if tv and (season is None or len(seasons) > 1):
            raise RuntimeError('跨季包或季号不明确，需人工确认后下载')
        candidate = resolution(getattr(meta, 'org_string', '') or getattr(meta, 'orginal_title', '') or '')
        candidate = getattr(meta, '_rss_resolution', candidate)
        covered = set()
        verified_low = set()
        verified_low_movie = False
        library_episodes = set((getattr(existing, 'seasons', None) or {}).get(season, []) or []) if tv and existing else set()
        # Completed transfers survive torrent removal and library-index delays.
        # Historical success alone is insufficient: the destination must still exist.
        if self.transferred:
            for row in self.transferred(ident, season):
                path = Path(row.dest or '')
                if not path.is_absolute() or path.suffix.lower() not in VIDEO:
                    continue
                try:
                    if not path.is_file() or path.stat().st_size <= 0:
                        continue
                except OSError as exc:
                    raise RuntimeError('无法核实整理目标文件，延后处理') from exc
                old_resolution = resolution(path.name)
                if not tv:
                    if blocks(candidate, old_resolution):
                        return '已成功整理且目标电影文件仍存在（同级或更高/未知分辨率）', None
                    verified_low_movie = True
                    continue
                pair = explicit_pairs(path.name)
                if pair and pair[0] == season:
                    if blocks(candidate, old_resolution):
                        covered.add(pair[1])
                    else:
                        verified_low.add(pair[1])
        if not tv and existing and not verified_low_movie:
            return '媒体库已有电影，尚无可靠1080p升级依据', None
        covered.update(library_episodes - verified_low)
        if tv and episodes and episodes.issubset(covered):
            return '已入库或成功整理，且目标集数仍存在', None
        servers = self.module.get_instances()
        if not servers:
            raise RuntimeError('没有可查询的qBittorrent下载器，延后处理')
        torrents = []
        for name, server in servers.items():
            result = server.get_torrents()
            if not result or result[0] is None or result[1]:
                raise RuntimeError('下载器查询失败，延后处理')
            torrents.extend((name, server, t) for t in result[0])
        rows = self.history.get_by_hashes([t['hash'] for _, _, t in torrents])
        for name, server, torrent in torrents:
            if torrent.get('state') in FAILED:
                continue
            row = rows.get(torrent['hash']) or rows.get(torrent['hash'].lower())
            if not row:
                # Unrecognized manually added downloads are not matched by fuzzy title.
                if 'MOVIEPILOT' in (torrent.get('tags') or ''):
                    raise RuntimeError('下载任务尚无媒体历史映射，延后处理')
                continue
            if (row.type, row.tmdbid) != ident:
                continue
            if getattr(row, 'downloader', None) and row.downloader != name:
                continue
            old_resolution = resolution(torrent.get('name') or getattr(row, 'torrent_name', ''))
            if not tv:
                if blocks(candidate, old_resolution):
                    return '同一电影已有同级或更高/未知分辨率任务', None
                continue
            files = server.get_files(torrent['hash'])
            if files is None:
                raise RuntimeError('无法读取同媒体任务文件，延后处理')
            pairs = selected_pairs(files)
            if pairs is None:
                row_seasons = {int(x) for x in re.findall(r'S(\d+)', row.seasons or '')}
                if not row_seasons or season in row_seasons:
                    raise RuntimeError('同季任务集数尚不明确，延后处理')
                continue
            for file in files:
                if file.get('priority', 1) == 0 or Path(file['name']).suffix.lower() not in VIDEO:
                    continue
                pair = explicit_pairs(Path(file['name']).name)
                file_resolution = resolution(Path(file['name']).name) or old_resolution
                if pair and pair[0] == season and blocks(candidate, file_resolution):
                    covered.add(pair[1])
        pending = json.loads(self.pending.read_text()) if self.pending.exists() else []
        now = time.time()
        pending = [p for p in pending if now - p['time'] < 120]
        for p in pending:
            if tuple(p['identity']) != ident:
                continue
            if not blocks(candidate, p.get('resolution', 0)):
                continue
            if not tv:
                return '同一电影刚刚提交下载', None
            if p['season'] == season:
                if not p['episodes'] or not episodes:
                    return '同季资源刚刚提交，等待任务信息', None
                covered.update(p['episodes'])
        if tv and episodes:
            missing = episodes - covered
            if not missing:
                return '同季集已在媒体库或下载任务中', None
            return None, missing if missing != episodes else None
        if tv and covered:
            raise RuntimeError('整季包存在集数重叠但缺少完整集数，需人工确认')
        return None, None

    def reserve(self, media, meta, hash_value, selected=None):
        now = time.time()
        entries = json.loads(self.pending.read_text()) if self.pending.exists() else []
        entries = [p for p in entries if now - p['time'] < 120]
        entries.append({'identity': identity(media), 'season': getattr(meta, 'begin_season', None),
                        'episodes': sorted(selected or getattr(meta, 'episode_list', None) or []),
                        'resolution': getattr(meta, '_rss_resolution', resolution(getattr(meta, 'org_string', ''))),
                        'hash': hash_value, 'time': now})
        temporary = self.pending.with_suffix('.tmp')
        temporary.write_text(json.dumps(entries, ensure_ascii=False))
        temporary.replace(self.pending)
