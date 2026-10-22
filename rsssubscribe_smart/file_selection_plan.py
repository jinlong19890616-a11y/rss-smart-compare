"""Offline qBittorrent file-selection planner.

This module never calls qBittorrent. It returns a plan that a future adapter
may apply with priority=0 for library episodes and priority=1 for missing ones.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import PurePosixPath
import json
import re
from pathlib import Path

VIDEO = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.webm', '.mpeg', '.mpg'}
PAIR_RE = re.compile(r'(?i)S(?P<s>\d{1,3})[ ._-]*E(?P<e>\d{1,4})(?!\d)')

@dataclass(frozen=True)
class FileDecision:
    index: int
    name: str
    action: str
    priority: int | None
    season: int | None = None
    episode: int | None = None
    reason: str = ''


def file_pair(name: str):
    """Return one unambiguous SxxEyy pair for a video filename."""
    if PurePosixPath(name).suffix.lower() not in VIDEO:
        return None
    matches = list(PAIR_RE.finditer(PurePosixPath(name).name))
    if len(matches) != 1:
        return None
    m = matches[0]
    if re.match(r'(?i)[ ._-]*E?\d', PurePosixPath(name).name[m.end():]):
        return None
    return int(m.group('s')), int(m.group('e'))


def build_plan(files: list[dict], season: int, existing: set[int], *, allow_nonvideo=False):
    """Build a safe plan. Unknown video names cause defer, not guessing."""
    decisions = []
    known_video = 0
    unknown_video = []
    for f in files:
        idx = int(f.get('index', f.get('id', -1)))
        name = str(f.get('name', ''))
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in VIDEO:
            if allow_nonvideo:
                decisions.append(FileDecision(idx, name, 'keep', None, reason='非视频文件，不改变优先级'))
            else:
                decisions.append(FileDecision(idx, name, 'defer', None, reason='包含非视频文件'))
            continue
        pair = file_pair(name)
        if not pair or pair[0] != season:
            unknown_video.append(name)
            decisions.append(FileDecision(idx, name, 'defer', None, reason='无法唯一识别本季集数'))
            continue
        known_video += 1
        ep = pair[1]
        if ep in existing:
            decisions.append(FileDecision(idx, name, 'skip', 0, season, ep, '媒体库已有该集'))
        else:
            decisions.append(FileDecision(idx, name, 'download', 1, season, ep, '媒体库缺少该集'))
    if unknown_video or known_video == 0:
        return {'status':'defer', 'reason':'存在无法明确识别的本季视频文件，拒绝猜测', 'decisions':[asdict(x) for x in decisions]}
    downloads = [x for x in decisions if x.action == 'download']
    if not downloads:
        return {'status':'skip', 'reason':'种子内视频集数全部已存在', 'decisions':[asdict(x) for x in decisions]}
    return {'status':'apply', 'reason':'只选择媒体库缺失集', 'decisions':[asdict(x) for x in decisions]}


def main(path: str):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    print(json.dumps(build_plan(data['files'], int(data['season']), set(data.get('existing', []))), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('fixture')
    main(ap.parse_args().fixture)
