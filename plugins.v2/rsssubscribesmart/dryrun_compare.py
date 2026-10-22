"""Offline dry-run comparison for RSS episode decisions.
No MoviePilot, qBittorrent, network, or filesystem media access is used.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

EPISODE_RE = re.compile(r"(?i)S(?P<season>\d{1,3})[ ._-]*E(?P<start>\d{1,4})(?:\s*[-~]\s*(?:S\d{1,3})?[ ._-]*E?(?P<end>\d{1,4}))?")

SEASON_ONLY_RE = re.compile(r"(?i)S(?P<season>\d{1,3})(?![ ._-]*E\d)")

def parse_episodes(title: str):
    m = EPISODE_RE.search(title or "")
    if m:
        season = int(m.group("season"))
        start = int(m.group("start"))
        end = int(m.group("end") or start)
        if end < start:
            return None
        return season, set(range(start, end + 1))
    m = SEASON_ONLY_RE.search(title or "")
    return (int(m.group("season")), None) if m else None

@dataclass
class Decision:
    title: str
    season: int | None
    candidate_episodes: list[int]
    library_episodes: list[int]
    missing_episodes: list[int]
    legacy: str
    smart: str
    note: str = ""


def compare_one(title: str, library: dict[int, Iterable[int]]) -> Decision:
    parsed = parse_episodes(title)
    if not parsed:
        return Decision(title, None, [], [], [], "无法识别，跳过/人工处理", "延后人工处理", "未识别到明确 SxxEyy 或范围")
    season, episodes = parsed
    existing = set(library.get(season, []))
    if episodes is None:
        return Decision(title, season, [], sorted(existing), [], "下载整季/整包", "先读取种子文件列表", "只有独立视频文件才能按缺失集选择；压缩包延后人工处理")
    missing = sorted(episodes - existing)
    candidate = sorted(episodes)
    if not missing:
        legacy = "已有集数全部覆盖：跳过"
        smart = "跳过"
        note = ""
    elif len(missing) == len(episodes):
        legacy = "下载整条 RSS 资源"
        smart = "下载全部候选集"
        note = "库中没有候选集"
    else:
        legacy = "可能下载整季/整包：存在重复风险"
        smart = "只下载缺失集"
        note = "qBittorrent 必须返回独立视频文件，压缩包无法按集拆分"
    return Decision(title, season, candidate, sorted(existing), missing, legacy, smart, note)


def compare_fixture(data: dict) -> list[Decision]:
    library_by_media = data.get("library") or {}
    # Backward-compatible fixture: a flat season->episodes map.
    if library_by_media and all(isinstance(v, list) for v in library_by_media.values()):
        library_by_media = {"__default__": library_by_media}
    rows = []
    for item in data.get("rss", []):
        library = library_by_media.get(str(item.get("tmdbid")), library_by_media.get("__default__", {}))
        library = {int(k): v for k, v in library.items()}
        rows.append(compare_one(item["title"], library))
    return rows


def main(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    decisions = compare_fixture(data)
    print(json.dumps([asdict(x) for x in decisions], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Offline smart RSS dry-run")
    ap.add_argument("fixture")
    main(ap.parse_args().fixture)
