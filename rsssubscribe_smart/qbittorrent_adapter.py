"""Small qBittorrent integration boundary for the smart RSS prototype.

The adapter is deliberately dependency-free. A real MoviePilot adapter can
implement the three methods used here; tests use FakeQbit only.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .file_selection_plan import build_plan

class QbitLike(Protocol):
    def add_torrent(self, torrent_url: str, save_path: str | None = None) -> str: ...
    def get_files(self, torrent_hash: str) -> list[dict]: ...
    def set_file_priority(self, torrent_hash: str, file_ids: list[int], priority: int) -> None: ...

@dataclass
class ApplyResult:
    torrent_hash: str
    status: str
    reason: str
    skipped_ids: list[int]
    download_ids: list[int]


def add_and_plan(qbit: QbitLike, torrent_url: str, season: int, existing: set[int], save_path: str | None = None) -> ApplyResult:
    """Add, inspect, and apply safe per-file priorities.

    The caller must provide a qBittorrent implementation. This function does
    not delete files or torrents. A defer plan is never applied.
    """
    torrent_hash = qbit.add_torrent(torrent_url, save_path=save_path)
    files = qbit.get_files(torrent_hash)
    plan = build_plan(files, season, existing)
    if plan['status'] == 'defer':
        return ApplyResult(torrent_hash, 'defer', plan['reason'], [], [])
    skipped = [x['index'] for x in plan['decisions'] if x['action'] == 'skip']
    downloads = [x['index'] for x in plan['decisions'] if x['action'] == 'download']
    if skipped:
        qbit.set_file_priority(torrent_hash, skipped, 0)
    if downloads:
        qbit.set_file_priority(torrent_hash, downloads, 1)
    return ApplyResult(torrent_hash, plan['status'], plan['reason'], skipped, downloads)
