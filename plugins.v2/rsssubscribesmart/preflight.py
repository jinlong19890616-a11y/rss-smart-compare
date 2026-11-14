"""Pure, fail-closed torrent preflight helpers; no downloader mutation."""
from pathlib import Path
import contextlib
import fcntl
import json
import re
import time
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


def looks_like_torrent(content) -> bool:
    """A bencoded .torrent always starts with a top-level dictionary marker.

    RSS endpoints under rate limiting or with expired links often answer with
    JSON/HTML while still returning HTTP 200. Feeding that payload to the
    bencode parser produces confusing errors on every single refresh cycle.
    """
    return (isinstance(content, (bytes, bytearray))
            and len(content) > 20 and bytes(content[:1]) == b'd')


def torrent_payload_diagnostic(content) -> str:
    """Short, credential-safe description of an unexpected payload."""
    if content is None:
        return 'empty response'
    if isinstance(content, (bytes, bytearray)):
        head = bytes(content[:96])
        head = re.sub(rb'(?i)(sign|token|passkey|authkey|uid|t)=[^&\s"\']+',
                      rb'\1=<redacted>', head)
        return f'bytes len={len(content)} head={head!r}'
    text = str(content)[:96]
    text = re.sub(r'(?i)(sign|token|passkey|authkey|uid|t)=[^&\s"\']+',
                  r'\1=<redacted>', text)
    return f'{type(content).__name__} head={text!r}'


class DeferCache:
    """Backoff for payload-level failures that cannot succeed on a later poll.

    Only deterministic failures belong here: a link that keeps returning a
    non-torrent JSON/HTML page, or a torrent whose file names can never be
    mapped to episodes. Download results are deliberately NOT cached here;
    qBittorrent tasks, download history, library state and the guard's
    pending reservations own that decision, so a better release or a genuine
    retry is never suppressed.
    """

    def __init__(self, root, ttl_seconds: int = 6 * 3600, max_entries: int = 2000):
        self.root = Path(root)
        self.path = self.root / 'rss-defer-backoff.json'
        self.lock_path = self.root / 'rss-defer-backoff.lock'
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._round = None

    @staticmethod
    def key(fingerprint) -> str:
        return '|'.join(str(part) for part in fingerprint)

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        now = time.time()
        return {k: v for k, v in data.items()
                if isinstance(v, dict) and 0 <= now - float(v.get('time', 0)) < self.ttl}

    @contextlib.contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def begin_round(self):
        """Load once per RSS refresh; avoids re-reading the file per item."""
        with self._locked():
            self._round = self._load()

    def is_deferred(self, fingerprint) -> bool:
        if self._round is None:
            self.begin_round()
        return self.key(fingerprint) in self._round

    def mark(self, fingerprint, reason: str):
        if self._round is None:
            self.begin_round()
        key = self.key(fingerprint)
        with self._locked():
            data = self._load()
            data[key] = {'time': time.time(), 'reason': str(reason)[:160]}
            if len(data) > self.max_entries:
                for old in sorted(data, key=lambda k: data[k].get('time', 0))[:len(data) - self.max_entries]:
                    data.pop(old, None)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False))
            temporary.replace(self.path)
            self._round = data
