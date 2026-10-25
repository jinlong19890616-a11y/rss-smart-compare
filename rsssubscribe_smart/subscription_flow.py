"""Checked, independently retryable subscription creation."""
def ensure_subscription(chain, media, meta, logger):
    season = getattr(meta, 'begin_season', None)
    seasons = list(getattr(meta, 'season_list', None) or [])
    if not getattr(media, 'tmdb_id', None) or season is None or len(seasons) != 1:
        logger.warning('RSS_SUBSCRIBE_DEFER: 缺少明确媒体身份或单季范围')
        return False
    try:
        if chain.exists(mediainfo=media, meta=meta):
            logger.info(f'RSS_SUBSCRIBE_EXISTS {media.title_year} S{season:02d}')
            return True
        result = chain.add(title=media.title, year=media.year, mtype=media.type,
                           tmdbid=media.tmdb_id, season=season, exist_ok=True,
                           username='RSS订阅')
        sid = result[0] if isinstance(result, tuple) and len(result) == 2 else None
        if sid:
            logger.info(f'RSS_SUBSCRIBE_CREATED {media.title_year} S{season:02d}: id={sid}')
            return True
        logger.warning(f'RSS_SUBSCRIBE_FAILED {media.title_year} S{season:02d}: 接口未返回订阅ID，下轮重试')
    except Exception:
        # Do not expose API payloads, URLs or credentials in logs.
        logger.warning(f'RSS_SUBSCRIBE_FAILED {media.title_year} S{season:02d}: 订阅接口异常，下轮重试')
    return False
