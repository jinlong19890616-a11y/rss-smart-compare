"""Season-aware repair of TMDB identities for RSS releases.

MoviePilot matches a bare title by name, sorts TMDB hits by ``first_air_date``
descending and returns the first exact-name hit.  When an old show gets a newer
namesake (``Would I Lie to You?`` 2007 vs the 2022 US remake), an ``S09``
release is attached to a one-season TMDB entry.  Custom identifier rules can
only fix titles somebody already noticed, which cannot work for an unknown
future release.

This module repairs that whole class of mistake without a word list:

1. Only when a TV release has an explicit season that the current TMDB entry
   cannot possibly contain -- both season capacity and first-air-year math must
   be impossible.  This excludes anime part numbering, daily soaps and shows
   that air several numbered seasons per year.
2. Only when another *same-name* TMDB entry can actually contain that season
   and its own first-air year makes the season number plausible.
3. Only when that replacement is unambiguous (a unique eligible entry, or a
   clearly dominant one by vote count).

Anything less certain is logged and left alone.  The download is never blocked
and never deferred by this module: a wrong identity is a metadata problem, not
a reason to lose a resource.
"""
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

_NON_ALNUM = re.compile(r"[^0-9a-z\u3400-\u9fff]+")

# One season of slack for late TMDB updates, and one year of slack for
# announcements/aired-future seasons.
_SEASON_SLACK = 1
_YEAR_SLACK = 1
# S01/S02 are too noisy: anime parts and split cours routinely disagree with
# TMDB here, and a two-season gap is not a useful namesake signal.
_MIN_SEASON = 3
_MAX_CANDIDATES = 10
_MIN_DOMINANT_VOTES = 20


def normalize_name(value: Any) -> str:
    """Case/punctuation insensitive comparison key for a show name."""
    return _NON_ALNUM.sub("", str(value or "").lower())


def season_capacity(source: Any) -> Optional[int]:
    """Highest real season TMDB knows about, from a MediaInfo or a TMDB dict."""
    if source is None:
        return None
    numbers: List[int] = []
    if isinstance(source, dict):
        seasons = source.get("seasons") or []
        if isinstance(seasons, dict):
            numbers.extend(n for n in seasons if isinstance(n, int) and n > 0)
        else:
            for item in seasons:
                if isinstance(item, dict):
                    number = item.get("season_number")
                    if isinstance(number, int) and number > 0:
                        numbers.append(number)
        total = source.get("number_of_seasons")
    else:
        seasons = getattr(source, "seasons", None) or {}
        if isinstance(seasons, dict):
            numbers.extend(n for n in seasons if isinstance(n, int) and n > 0)
        total = getattr(source, "number_of_seasons", None)
    if isinstance(total, int) and total > 0:
        numbers.append(total)
    return max(numbers) if numbers else None


def first_air_year(source: Any) -> Optional[int]:
    if isinstance(source, dict):
        raw = source.get("first_air_date") or source.get("year")
    else:
        raw = getattr(source, "first_air_date", None) or getattr(source, "year", None)
    try:
        year = int(str(raw)[:4])
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def year_math_implausible(first_year: Optional[int], season: Optional[int],
                          current_year: int, slack: int = _YEAR_SLACK) -> bool:
    """A show first aired in 2022 cannot have an S09 release in 2026."""
    if not first_year or not season:
        return False
    return first_year + season - 1 > current_year + slack


def mismatch_reason(mediainfo: Any, season: Optional[int],
                    current_year: int) -> Optional[str]:
    """Return a reason to attempt repair, or None when the identity looks sane."""
    if not mediainfo or not season or season < _MIN_SEASON:
        return None
    capacity = season_capacity(mediainfo)
    if capacity is None:
        return None
    if season <= capacity + _SEASON_SLACK:
        return None
    year = first_air_year(mediainfo)
    if not year or not year_math_implausible(year, season, current_year):
        # Long-running shows with several numbered seasons per year, or sites
        # using cumulative numbering, are normal. Never touch those.
        return None
    return (f"S{season:02d} 超出 TMDB 已知 {capacity} 季，"
            f"且 {year} 年首播不可能有第 {season} 季")


def choose_replacement(candidates: Optional[List[dict]], *, query: str,
                       season: int, current_year: int,
                       wrong_id: Optional[int]) -> Tuple[Optional[dict], str]:
    """Pick a same-name, season-capable TMDB entry, or refuse to guess."""
    key = normalize_name(query)
    if not key:
        return None, "识别名称为空"
    eligible: List[dict] = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        try:
            cid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if wrong_id is not None and cid == int(wrong_id):
            continue
        if key not in (normalize_name(item.get("name")),
                       normalize_name(item.get("original_name"))):
            continue
        capacity = season_capacity(item)
        if capacity is None or capacity + _SEASON_SLACK < season:
            continue
        year = first_air_year(item)
        if not year or year_math_implausible(year, season, current_year):
            continue
        eligible.append({
            "id": cid,
            "name": item.get("name"),
            "year": year,
            "capacity": capacity,
            "vote_count": item.get("vote_count") or 0,
            "popularity": item.get("popularity") or 0,
        })
    if not eligible:
        return None, "没有同名且季数足够的其他 TMDB 条目"
    eligible.sort(key=lambda x: (-x["vote_count"], -x["popularity"], x["year"], x["id"]))
    best = eligible[0]
    if len(eligible) > 1:
        runner = eligible[1]
        if best["vote_count"] < _MIN_DOMINANT_VOTES \
                or best["vote_count"] < 2 * runner["vote_count"]:
            return None, "多个同名条目季数都够，无法唯一确定"
    return best, "唯一同名长季条目"


class SeasonIdentityFixer:
    """Per-RSS-round repair helper. All remote access is injected by the plugin."""

    def __init__(self, *, collect_candidates, recognize_by_id, logger=None,
                 enabled: bool = True, current_year: Optional[int] = None):
        self._collect = collect_candidates
        self._recognize = recognize_by_id
        self._logger = logger
        self.enabled = bool(enabled)
        self.current_year = current_year or datetime.date.today().year
        self._cache: Dict[Tuple[str, int, Optional[int]], Tuple[Any, str]] = {}
        self.stats = {"suspect": 0, "fixed": 0, "skipped": 0}

    def _log(self, level: str, message: str) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(message)

    def repair(self, mediainfo: Any, *, names: List[str], season: Optional[int],
               query_title: str = "", is_tv: bool = True) -> Any:
        """Return the original or a corrected MediaInfo; never returns None."""
        if not self.enabled or not is_tv or not mediainfo:
            return mediainfo
        reason = mismatch_reason(mediainfo, season, self.current_year)
        if not reason:
            return mediainfo
        self.stats["suspect"] += 1
        wrong_id = getattr(mediainfo, "tmdb_id", None)
        query_names, seen = [], set()
        for value in names or []:
            key = normalize_name(value)
            if key and key not in seen:
                seen.add(key)
                query_names.append(str(value))
        if not query_names:
            return mediainfo
        cache_key = (normalize_name(query_names[0]), int(season), wrong_id)
        first_time = cache_key not in self._cache
        if first_time:
            self._cache[cache_key] = self._decide(
                query_names, int(season), wrong_id, query_title)
        replacement, status = self._cache[cache_key]
        if replacement is None:
            if first_time:
                self.stats["skipped"] += 1
                self._log("warning",
                          f"RSS_SEASON_IDENTITY_SUSPECT {query_names[0]} S{season:02d}: "
                          f"{reason}；{status}，保持原识别结果继续处理（不影响下载）")
            return mediainfo
        if first_time:
            self.stats["fixed"] += 1
            self._log(
                "info",
                f"RSS_SEASON_IDENTITY_FIX {query_names[0]} S{season:02d}: {reason}；"
                f"{status}，改绑 {getattr(replacement, 'title_year', None)} "
                f"(TMDB {getattr(replacement, 'tmdb_id', None)})"
            )
        return replacement

    def _decide(self, query_names: List[str], season: int, wrong_id: Optional[int],
                query_title: str) -> Tuple[Any, str]:
        last_status = "没有可用的同名 TMDB 条目"
        for name in query_names:
            try:
                candidates = self._collect(name) or []
            except Exception as err:
                last_status = f"TMDB 同名搜索失败 ({type(err).__name__})"
                continue
            best, status = choose_replacement(
                candidates, query=name, season=season,
                current_year=self.current_year, wrong_id=wrong_id)
            last_status = status
            if not best:
                continue
            try:
                replacement = self._recognize(best["id"], query_title or name)
            except Exception as err:
                last_status = f"按 TMDB {best['id']} 重新识别失败 ({type(err).__name__})"
                continue
            if not replacement:
                last_status = f"按 TMDB {best['id']} 重新识别无结果"
                continue
            capacity = season_capacity(replacement)
            if capacity is not None and capacity + _SEASON_SLACK < season:
                last_status = f"候选 TMDB {best['id']} 重新识别后季数仍不足"
                continue
            return replacement, status
        return None, last_status
