"""只根据显式配置的主机匹配站点，不读取凭证或推断域名别名。"""
import ipaddress
import re
from urllib.parse import urlsplit


def _host(value, *, domain=False):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if any(c.isspace() for c in value) or '\\' in value:
        return None
    if domain and '://' not in value:
        value = 'https://' + value
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in ('http', 'https') or not parsed.netloc
                or parsed.username is not None or parsed.password is not None):
            return None
        parsed.port
        host = (parsed.hostname or '').removesuffix('.').encode('idna').decode('ascii').lower()
    except (ValueError, UnicodeError):
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split('.')
    if (len(labels) < 2 or len(host) > 253
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                   for label in labels)):
        return None
    return host


def snapshot_sites(sites):
    """丢弃原始URL，仅保留匹配所需的ID、名称和显式主机。"""
    snapshots = []
    for site in sites:
        site_id, name = site.id, site.name
        if (not isinstance(site_id, int) or isinstance(site_id, bool) or site_id <= 0
                or not isinstance(name, str) or not name.strip()):
            continue
        hosts = frozenset(host for host in (
            _host(site.domain, domain=True), _host(site.url), _host(site.rss)
        ) if host)
        if hosts:
            snapshots.append((site_id, name, hosts))
    return tuple(snapshots)


def _within_host(host, anchor):
    if host == anchor:
        return True
    try:
        ipaddress.ip_address(anchor)
        return False
    except ValueError:
        return host.endswith('.' + anchor)


def _candidates(value, sites):
    host = _host(value)
    if not host:
        return set()
    return {(site_id, name) for site_id, name, hosts in sites
            if any(_within_host(host, anchor) for anchor in hosts)}


def match_site(sites, *, link='', enclosure='', source_feed=''):
    """直接链接优先；有来源链接但未知时不以feed冒认其站点。"""
    direct = [value for value in (link, enclosure)
              if value is not None and (not isinstance(value, str) or value.strip())]
    candidates = set()
    for value in direct:
        candidates.update(_candidates(value, sites))
    if not direct:
        candidates = _candidates(source_feed, sites)
    return next(iter(candidates)) if len(candidates) == 1 else None
