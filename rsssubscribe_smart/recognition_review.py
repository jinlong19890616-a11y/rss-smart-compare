"""基于结构化证据与真实季集的身份复核，远程依赖由调用方注入。"""
import re
from dataclasses import dataclass
from html import unescape


def name_key(value):
    return re.sub(r'[^0-9a-z\u3400-\u9fff]+', '', str(value or '').lower())


def year_of(value):
    match = re.match(r'^(19\d{2}|20\d{2})(?:\D|$)', str(value or '').strip())
    return int(match[1]) if match else None


def structured_evidence(description):
    # 只读取显式字段；简介、演员、站点标签及其正文均不参与强类别判断。
    text = unescape(str(description or ''))
    text = re.sub(r'(?i)<(?:br\s*/?|/p|/div|/tr)>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.translate(str.maketrans('譯類別簡劇動畫導員國語製標籤', '译类别简剧动画导演国语制标签'))
    labels = ('片名', '译名', '中文名', '年代', '年份', '类别', '类型',
              '简介', '剧情', '标签', '主演', '演员', '导演', '产地', '国家',
              '地区', '语言', '字幕', '集数', '片长', '上映日期', '首播',
              '豆瓣评分', 'IMDb评分', '制片国家')
    label_pattern = '|'.join(r'[ \t\u3000]*'.join(label) for label in labels)
    # ◎/行首/竖线后的标签可无冒号；无分隔拼接的字段必须有冒号。
    pattern = (rf'(?:^|[\n|｜◎●◆])[ \t\u3000]*({label_pattern})[ \t\u3000]*[:：]?'
               rf'|({label_pattern})[ \t\u3000]*[:：]')
    matches = list(re.finditer(pattern, text))
    fields = {}
    for index, match in enumerate(matches):
        key = re.sub(r'[ \t\u3000]', '', match[1] or match[2])
        # 简介/剧情后的文本不再具有结构化可信度，包括正文中的伪字段。
        if key in ('简介', '剧情', '标签'):
            break
        if match[2] and not fields:
            # 无字段起点的普通正文不能靠内嵌冒号变成结构化字段。
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = re.split(r'[\n|｜◎●◆]', text[match.end():end], maxsplit=1)[0].strip()
        fields.setdefault(key, []).append(value)
    genres = set()
    for value in fields.get('类别', []) + fields.get('类型', []):
        tokens = set(re.split(r'[/、,，;；\s]+', value.strip()))
        if tokens & {'动画', 'Animation'}:
            genres.add(16)
        if tokens & {'真人秀', 'Reality'}:
            genres.add(10764)
    years = {year_of(v) for key in ('年代', '年份') for v in fields.get(key, [])} - {None}
    names = [v for key in ('片名', '译名', '中文名') for v in fields.get(key, []) if v]
    return genres, next(iter(years)) if len(years) == 1 else None, names


@dataclass
class ReviewResult:
    media: object
    season: int
    blocked: bool = False
    reason: str = ''
    changed: bool = False


def apply_review(meta, result):
    """在私有的资源 MetaInfo 上同步身份；不修改共享 MediaInfo。"""
    if result.changed:
        meta.tmdbid = int(result.media.tmdb_id)
        meta.begin_season = result.season
        meta.end_season = None
        meta.total_season = 1
        meta.year = getattr(result.media, 'year', None)


class RecognitionReviewer:
    def __init__(self, *, collect_candidates, get_detail, get_season,
                 recognize_by_id, logger=None, enabled=True):
        self.collect = collect_candidates
        self.detail = get_detail
        self.season_detail = get_season
        self.recognize = recognize_by_id
        self.logger = logger
        self.enabled = enabled
        self.cache = {}

    def _get(self, key, loader):
        if key not in self.cache:
            try:
                self.cache[key] = loader()
            except Exception:
                # 不记录远程异常正文，避免其中携带认证 URL。
                self.cache[key] = None
        return self.cache[key]

    def _episodes(self, cid, season):
        data = self._get(('season', cid, season), lambda: self.season_detail(cid, season))
        if not isinstance(data, dict) or data.get('season_number') != season:
            return None
        episodes = data.get('episodes') or []
        numbers = {e['episode_number'] for e in episodes if isinstance(e, dict)
                   and isinstance(e.get('episode_number'), int) and e['episode_number'] > 0
                   and e.get('season_number', season) == season}
        return numbers or None

    def _log(self, tag, reason):
        if self.logger:
            self.logger.warning(f'{tag} {reason}')

    def review(self, media, *, names, season, episodes=(), description='', query_title=''):
        original = ReviewResult(media, season)
        if not self.enabled or not media or not season:
            return original
        cid = int(media.tmdb_id)
        expected, year, field_names = structured_evidence(description)
        requested = set(episodes or ())
        # 无结构化证据且无目标集数时，不为正常未知元数据强加门槛。
        if not expected and not requested:
            return original
        detail = self._get(('detail', cid), lambda: self.detail(cid))
        if not isinstance(detail, dict):
            return original
        genres = set(detail.get('genre_ids') or [])
        type_conflict = bool(expected and genres and not expected <= genres)
        summaries = [s for s in detail.get('seasons', [])
                     if isinstance(s, dict) and s.get('season_number', 0) > 0]
        source = next((s for s in summaries if s['season_number'] == season), None)
        real = None
        # 只有摘要容量不够时才加载完整季；确认不是稀疏编号/摘要滞后。
        if requested and source and isinstance(source.get('episode_count'), int) \
                and max(requested) > source['episode_count']:
            real = self._episodes(cid, season)
        capacity_conflict = bool(real and requested and max(requested) > max(real))
        show_year = year_of(detail.get('first_air_date'))
        season_years = [year_of(s.get('air_date')) for s in summaries]
        # 年份可能指作品首播或任一季首播；数据缺失不当作年份矛盾。
        year_conflict = bool(year and show_year and season_years and all(season_years)
                             and year not in {show_year, *season_years})
        if not type_conflict and not (capacity_conflict and year_conflict):
            if capacity_conflict:
                original.reason = f'TMDB {cid} S{season:02d} 容量异常但无独立身份冲突，可能为季集滞后或累计编号；保留原识别，不猜偏移'
                self._log('RSS_RECOGNITION_REVIEW_SUSPECT', original.reason)
            return original
        reasons = [f'TMDB {cid} S{season:02d}']
        if year_conflict:
            reasons.append('结构化年份与作品及所有已知季首播年份不符')
        if type_conflict:
            reasons.append('结构化类别与当前条目不符')
        if capacity_conflict:
            reasons.append('目标集超出当前条目真实季集容量')
        query_names = list(dict.fromkeys(str(n) for n in list(names) + field_names if n))
        keys = {name_key(n) for n in query_names} - {''}
        candidates = {cid: detail}
        incomplete = False
        for name in query_names:
            hits = self._get(('search', name_key(name)), lambda n=name: self.collect(n))
            if hits is None:
                incomplete = True
            for hit in hits or []:
                if isinstance(hit, dict) and hit.get('id'):
                    candidates[int(hit['id'])] = hit
        options = {}
        for candidate_id, hit in candidates.items():
            data = self._get(('detail', candidate_id), lambda i=candidate_id: self.detail(i))
            if not isinstance(data, dict):
                incomplete = True
                continue
            aliases = [data.get('name'), data.get('original_name')] + list(data.get('names') or [])
            if not keys & {name_key(n) for n in aliases if isinstance(n, str)}:
                continue
            if expected and not expected <= set(data.get('genre_ids') or []):
                continue
            for target in data.get('seasons') or []:
                if not isinstance(target, dict):
                    continue
                sn = target.get('season_number', 0)
                if not isinstance(sn, int) or sn <= 0:
                    continue
                season_year = year_of(target.get('air_date'))
                show_year = year_of(data.get('first_air_date'))
                if year and year not in (show_year, season_year):
                    continue
                if sn != season:
                    # 不猜累计编号、不做跨季偏移；仅允许带可靠年份且从E01开始的整季重标。
                    if season != 1 or not year or season_year != year or not requested \
                            or min(requested) != 1 or requested != set(range(1, max(requested) + 1)):
                        continue
                elif not requested and not (expected and year):
                    continue
                available = self._episodes(candidate_id, sn)
                if available is None:
                    incomplete = True
                    continue
                if requested and not requested <= available:
                    continue
                if sn != season and requested != available:
                    # 局部包可能是累计编号；整季重标还须完整覆盖目标季真实集清单。
                    continue
                if candidate_id != cid and not expected and not year:
                    # 仅容量异常不足以证明新身份。
                    continue
                options[(candidate_id, sn)] = data
        if len(options) != 1 or incomplete:
            reason = '；'.join(reasons) + ('；候选查询不完整/远程失败' if incomplete else
                                        '；候选或季集映射有歧义' if options else '；无可靠候选或季集映射')
            self._log('RSS_RECOGNITION_REVIEW_BLOCK', reason)
            return ReviewResult(media, season, True, reason)
        (target_id, target_season), data = next(iter(options.items()))
        replacement = media if target_id == cid else self._get(
            ('recognize', target_id, query_title), lambda: self.recognize(target_id, query_title))
        recognized_year = year_of(getattr(replacement, 'year', None))
        detail_year = year_of(data.get('first_air_date'))
        recognized_genres = set(getattr(replacement, 'genre_ids', None) or [])
        required_genres = expected | (set(data.get('genre_ids') or []) & {16, 10764})
        genre_conflict = bool(recognized_genres and not required_genres <= recognized_genres)
        if not replacement or int(getattr(replacement, 'tmdb_id', 0) or 0) != target_id \
                or (recognized_year and detail_year and recognized_year != detail_year) or genre_conflict:
            reason = '已证实身份矛盾，但候选重新识别失败或年份/类别不一致'
            self._log('RSS_RECOGNITION_REVIEW_BLOCK', reason)
            return ReviewResult(media, season, True, reason)
        reason = '；'.join(reasons) + f'；唯一真实季集匹配 TMDB {target_id} S{season:02d}->S{target_season:02d}'
        self._log('RSS_RECOGNITION_REVIEW_FIX', reason)
        return ReviewResult(replacement, target_season, reason=reason, changed=True)
