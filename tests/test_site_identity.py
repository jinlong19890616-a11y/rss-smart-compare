"""站点匹配的纯函数回归；只使用虚构URL与凭证。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N

sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from site_identity import match_site, snapshot_sites


def site(site_id=1, name='M-Team', domain='m-team.cc',
         url='https://m-team.cc/', rss='https://rss.m-team.cc/feed?token=fake'):
    return N(id=site_id, name=name, domain=domain, url=url, rss=rss)


class SiteIdentityTests(unittest.TestCase):
    def setUp(self):
        self.sites = snapshot_sites([site()])

    def test_details_host(self):
        self.assertEqual(match_site(self.sites, link='https://m-team.cc/details/1'), (1, 'M-Team'))

    def test_download_host(self):
        self.assertEqual(match_site(self.sites, enclosure='https://m-team.cc/download/1'), (1, 'M-Team'))

    def test_domain_allows_rss_subdomain(self):
        self.assertEqual(match_site(self.sites, link='https://rss.m-team.cc/details/1'), (1, 'M-Team'))

    def test_domain_allows_sibling_subdomains(self):
        self.assertEqual(match_site(self.sites, link='https://kp.m-team.cc/details/1',
                                    enclosure='https://dl.m-team.cc/download/1'), (1, 'M-Team'))

    def test_malicious_suffix(self):
        for host in ('m-team.cc.evil.test', 'rss.m-team.cc.evil.test', 'notm-team.cc',
                     'm-team-cc.test', 'evil-m-team.cc'):
            with self.subTest(host=host):
                self.assertIsNone(match_site(self.sites, link='https://' + host + '/1'))

    def test_unknown_alternate_is_not_alias(self):
        self.assertIsNone(match_site(self.sites, link='https://m-team.io/details/1'))

    def test_explicit_alternate_url_is_allowed(self):
        sites = snapshot_sites([site(url='https://alternate.test/')])
        self.assertEqual(match_site(sites, link='https://download.alternate.test/1'), (1, 'M-Team'))

    def test_explicit_alternate_rss_is_allowed(self):
        sites = snapshot_sites([site(rss='https://rss.other.test/feed')])
        self.assertEqual(match_site(sites, enclosure='https://dl.rss.other.test/1'), (1, 'M-Team'))

    def test_siblings_not_inferred_without_parent_anchor(self):
        sites = snapshot_sites([site(domain='kp.m-team.cc', url='https://kp.m-team.cc/',
                                     rss='https://rss.m-team.cc/feed')])
        self.assertIsNone(match_site(sites, link='https://dl.m-team.cc/1'))
        self.assertIsNone(match_site(sites, link='https://m-team.cc/1'))

    def test_public_suffix_is_not_guessed(self):
        sites = snapshot_sites([site(domain='a.example.co.uk', url='', rss='')])
        self.assertIsNone(match_site(sites, link='https://b.example.co.uk/1'))
        self.assertIsNone(match_site(sites, link='https://example.co.uk/1'))
        self.assertEqual(match_site(sites, link='https://dl.a.example.co.uk/1'), (1, 'M-Team'))

    def test_source_feed_fallback_without_direct_urls(self):
        self.assertEqual(match_site(self.sites, source_feed='https://rss.m-team.cc/feed'), (1, 'M-Team'))

    def test_blank_direct_urls_allow_feed(self):
        self.assertEqual(match_site(self.sites, link='  ', enclosure=None,
                                    source_feed='https://rss.m-team.cc/feed'), (1, 'M-Team'))

    def test_unknown_third_party_blocks_feed_fallback(self):
        for field in ('link', 'enclosure'):
            with self.subTest(field=field):
                self.assertIsNone(match_site(self.sites, **{field: 'https://third.test/1'},
                                             source_feed='https://rss.m-team.cc/feed'))

    def test_direct_match_has_priority_over_conflicting_feed(self):
        sites = snapshot_sites([site(), site(2, 'Other', 'other.test', '', '')])
        self.assertEqual(match_site(sites, link='https://m-team.cc/1',
                                    source_feed='https://other.test/feed'), (1, 'M-Team'))

    def test_unknown_feed_does_not_override_direct_match(self):
        self.assertEqual(match_site(self.sites, enclosure='https://rss.m-team.cc/1',
                                    source_feed='https://third.test/feed'), (1, 'M-Team'))

    def test_known_enclosure_can_identify_unknown_details(self):
        self.assertEqual(match_site(self.sites, link='https://third.test/1',
                                    enclosure='https://m-team.cc/1'), (1, 'M-Team'))

    def test_known_details_can_identify_unknown_enclosure(self):
        self.assertEqual(match_site(self.sites, link='https://m-team.cc/1',
                                    enclosure='https://third.test/1'), (1, 'M-Team'))

    def test_conflicting_direct_hosts_do_not_use_feed(self):
        sites = snapshot_sites([site(), site(2, 'Other', 'other.test', '', '')])
        self.assertIsNone(match_site(sites, link='https://m-team.cc/1',
                                     enclosure='https://other.test/1',
                                     source_feed='https://m-team.cc/feed'))

    def test_multiple_sites_on_same_host(self):
        sites = snapshot_sites([site(), site(2, 'Other')])
        self.assertIsNone(match_site(sites, link='https://m-team.cc/1'))

    def test_overlapping_parent_child_config_is_ambiguous(self):
        sites = snapshot_sites([site(), site(2, 'RSS', 'rss.m-team.cc', '', '')])
        self.assertIsNone(match_site(sites, link='https://rss.m-team.cc/1'))

    def test_ambiguous_feed(self):
        sites = snapshot_sites([site(), site(2, 'Other')])
        self.assertIsNone(match_site(sites, source_feed='https://m-team.cc/feed'))

    def test_ambiguous_details_not_resolved_by_enclosure(self):
        sites = snapshot_sites([site(), site(2, 'RSS', 'rss.m-team.cc', '', '')])
        self.assertIsNone(match_site(sites, link='https://rss.m-team.cc/1',
                                     enclosure='https://m-team.cc/1'))

    def test_case_trailing_dot_and_port(self):
        sites = snapshot_sites([site(domain='M-TEAM.CC.', url='', rss='')])
        self.assertEqual(match_site(sites, link='HTTPS://RSS.M-TEAM.CC.:443/1'), (1, 'M-Team'))

    def test_nested_query_url_is_never_parsed(self):
        self.assertIsNone(match_site(self.sites,
                                     link='https://third.test/?next=https://m-team.cc/1',
                                     source_feed='https://m-team.cc/feed'))

    def test_config_query_url_is_never_an_anchor(self):
        sites = snapshot_sites([site(domain='', url='https://other.test/?u=https://m-team.cc/', rss='')])
        self.assertIsNone(match_site(sites, link='https://m-team.cc/1'))

    def test_non_http_urls_do_not_match_or_trigger_feed(self):
        for value in ('ftp://m-team.cc/1', 'magnet:?xt=https://m-team.cc/1',
                      '//m-team.cc/1', '/details/1', 'javascript:https://m-team.cc/1'):
            with self.subTest(value=value):
                self.assertIsNone(match_site(self.sites, link=value,
                                             source_feed='https://m-team.cc/feed'))

    def test_non_http_config_urls_are_not_anchors(self):
        sites = snapshot_sites([site(domain='ftp://m-team.cc', url='ftp://m-team.cc',
                                     rss='magnet:?xt=https://m-team.cc/')])
        self.assertEqual(sites, ())

    def test_invalid_urls_do_not_match(self):
        for value in ('https://m-team.cc:bad/1', 'https://[invalid', 'https:///m-team.cc',
                      'https://m-team.cc\\@evil.test/', 'https://m-team.cc /',
                      'https://m-team.cc..', 'https://-bad.m-team.cc/'):
            with self.subTest(value=value):
                self.assertIsNone(match_site(self.sites, link=value))

    def test_url_credentials_are_not_trusted(self):
        for value in ('https://m-team.cc@evil.test/', 'https://fake:secret@m-team.cc/'):
            with self.subTest(value=value):
                self.assertIsNone(match_site(self.sites, enclosure=value))

    def test_invalid_types_do_not_match(self):
        for value in (False, 123, {}, []):
            with self.subTest(value=value):
                self.assertIsNone(match_site(self.sites, link=value,
                                             source_feed='https://m-team.cc/feed'))

    def test_empty_sites_and_unknown(self):
        self.assertIsNone(match_site((), link='https://m-team.cc/1'))
        self.assertIsNone(match_site(self.sites))
        self.assertIsNone(match_site(self.sites, source_feed='https://unknown.test/feed'))

    def test_snapshot_does_not_retain_credentials_or_original_urls(self):
        self.assertEqual(self.sites, ((1, 'M-Team', frozenset({'m-team.cc', 'rss.m-team.cc'})),))

    def test_duplicate_same_identity_is_not_conflict(self):
        sites = snapshot_sites([site(), site()])
        self.assertEqual(match_site(sites, link='https://m-team.cc/1'), (1, 'M-Team'))

    def test_invalid_identity_is_not_labelled(self):
        for row in (site(site_id=None), site(site_id=0), site(site_id=True),
                    site(site_id='1'), site(name=''), site(name=None)):
            with self.subTest(site_id=row.id, name=row.name):
                self.assertEqual(snapshot_sites([row]), ())

    def test_ipv4_exact_only(self):
        sites = snapshot_sites([site(domain='127.0.0.1', url='', rss='')])
        self.assertEqual(match_site(sites, link='http://127.0.0.1/1'), (1, 'M-Team'))
        self.assertIsNone(match_site(sites, link='http://evil.127.0.0.1/1'))

    def test_ipv6_exact(self):
        sites = snapshot_sites([site(domain='http://[::1]', url='', rss='')])
        self.assertEqual(match_site(sites, link='http://[::1]:8080/1'), (1, 'M-Team'))

    def test_input_not_mutated(self):
        row = site()
        before = vars(row).copy()
        sites = snapshot_sites([row])
        match_site(sites, link='https://m-team.cc/1')
        self.assertEqual(vars(row), before)


if __name__ == '__main__':
    unittest.main()
