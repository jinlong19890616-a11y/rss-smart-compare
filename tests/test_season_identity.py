import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N

sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))
from season_identity import (SeasonIdentityFixer, choose_replacement,
                             first_air_year, mismatch_reason, normalize_name,
                             season_capacity, year_math_implausible)


def show(cid, name, original, year, seasons, votes, pop=1.0):
    return {
        "id": cid, "name": name, "original_name": original,
        "first_air_date": f"{year}-01-01", "number_of_seasons": seasons,
        "seasons": [{"season_number": i} for i in range(1, seasons + 1)],
        "vote_count": votes, "popularity": pop,
    }


WILTY = [
    show(4775, "真的不骗你", "Would I Lie to You?", 2007, 19, 135, 27.2),
    show(158196, "Would I Lie to You?", "Would I Lie to You?", 2022, 1, 4),
    show(158741, "Would I Lie to You?", "Would I Lie to You?", 2022, 2, 3),
    show(119652, "Would I Lie To You? (NZ)", "Would I Lie To You? (NZ)", 2012, 1, 1),
]
SNL = [
    show(1667, "周六夜现场", "Saturday Night Live", 1975, 52, 550, 134.1),
    show(288670, "Saturday Night Live UK", "Saturday Night Live UK", 2026, 2, 19),
    show(156102, "Saturday Night Live", "Saturday Night Live", 2012, 1, 0),
    show(65597, "Saturday Night Live", "Saturday Night Live", 2016, 1, 1),
]
ALONE = [
    show(63726, "荒野独居", "Alone", 2015, 13, 115, 12.7),
    show(231625, "荒野独居之英国季", "Alone", 2023, 1, 8),
    show(339044, "Alone", "Alone", 2026, 1, 0),
    show(254080, "Alone", "Alone", 2025, 1, 0),
    show(1095, "攻壳机动队 STAND ALONE COMPLEX", "攻殻機動隊 STAND ALONE COMPLEX",
         2002, 2, 455, 16.3),
]


def media(tmdb_id, year, seasons, name=""):
    return N(tmdb_id=tmdb_id, year=str(year), first_air_date=f"{year}-01-01",
             number_of_seasons=seasons,
             seasons={i: list(range(1, 10)) for i in range(1, seasons + 1)},
             title=name or str(tmdb_id), title_year=f"{name or tmdb_id} ({year})")


class NameAndSeasonTests(unittest.TestCase):
    def test_normalize_strips_case_and_punctuation(self):
        self.assertEqual(normalize_name("Would I Lie To You"),
                         normalize_name("Would I Lie to You?"))
        self.assertEqual(normalize_name("Saturday Night Live"), "saturdaynightlive")
        self.assertEqual(normalize_name(None), "")

    def test_capacity_from_mediainfo_and_raw_detail(self):
        self.assertEqual(season_capacity(media(1, 2007, 19)), 19)
        self.assertEqual(season_capacity(WILTY[0]), 19)
        self.assertIsNone(season_capacity(N(seasons={}, number_of_seasons=None)))

    def test_capacity_ignores_specials_season_zero(self):
        detail = {"seasons": [{"season_number": 0}, {"season_number": 3}],
                  "number_of_seasons": None}
        self.assertEqual(season_capacity(detail), 3)

    def test_year_math(self):
        self.assertTrue(year_math_implausible(2022, 9, 2026))
        self.assertFalse(year_math_implausible(1972, 54, 2026))
        self.assertFalse(year_math_implausible(None, 9, 2026))

    def test_first_air_year(self):
        self.assertEqual(first_air_year(N(year="2007")), 2007)
        self.assertEqual(first_air_year({"first_air_date": "2016-09-01"}), 2016)
        self.assertIsNone(first_air_year(N(year=None)))


class MismatchGateTests(unittest.TestCase):
    def test_namesake_reboot_is_suspect(self):
        self.assertIn("S09", mismatch_reason(media(158196, 2022, 1), 9, 2026))

    def test_season_inside_capacity_is_fine(self):
        self.assertIsNone(mismatch_reason(media(4775, 2007, 19), 9, 2026))

    def test_long_running_numbering_drift_is_not_touched(self):
        # Marketplace 1972 / S54, The Fifth Estate 1976 / S52, anime split cours.
        for year, season, total in ((1972, 54, 7), (1976, 52, 17),
                                    (2021, 4, 1), (2023, 3, 1), (2017, 10, 3)):
            self.assertIsNone(mismatch_reason(media(1, year, total), season, 2026))

    def test_missing_or_low_season_is_ignored(self):
        self.assertIsNone(mismatch_reason(media(1, 2022, 1), None, 2026))
        self.assertIsNone(mismatch_reason(media(1, 2022, 1), 2, 2026))
        self.assertIsNone(mismatch_reason(N(seasons={}, number_of_seasons=None,
                                           year="2022", tmdb_id=1), 9, 2026))

    def test_implausible_but_multi_season_show_is_only_a_suspect(self):
        # Unreported World: S50 vs 42 seasons. The gate fires, but there is no
        # namesake with 50 seasons, so repair must keep the original identity.
        self.assertIn("S50", mismatch_reason(media(16108, 2000, 42), 50, 2026))


class CandidateChoiceTests(unittest.TestCase):
    def pick(self, rows, query, season, wrong):
        return choose_replacement(rows, query=query, season=season,
                                  current_year=2026, wrong_id=wrong)

    def test_wilty_picks_2007_bbc_show(self):
        best, _ = self.pick(WILTY, "Would I Lie To You", 9, 158196)
        self.assertEqual(best["id"], 4775)

    def test_snl_picks_1975_show(self):
        best, _ = self.pick(SNL, "Saturday Night Live", 52, 65597)
        self.assertEqual(best["id"], 1667)

    def test_alone_picks_2015_show_not_popular_unrelated_anime(self):
        best, _ = self.pick(ALONE, "Alone", 11, 339044)
        self.assertEqual(best["id"], 63726)

    def test_no_other_namesake_refuses_to_guess(self):
        best, status = self.pick([show(135657, "废柴的一日三餐", "백수세끼", 2021, 1, 9)],
                                 "废柴的一日三餐", 9, 135657)
        self.assertIsNone(best)
        self.assertIn("没有同名", status)

    def test_two_equally_strong_candidates_refuse_to_guess(self):
        rows = [show(1, "Same Show", "Same Show", 2005, 12, 100),
                show(2, "Same Show", "Same Show", 2006, 12, 90),
                show(3, "Same Show", "Same Show", 2025, 1, 0)]
        best, status = self.pick(rows, "Same Show", 10, 3)
        self.assertIsNone(best)
        self.assertIn("无法唯一确定", status)

    def test_candidate_that_is_itself_too_new_is_rejected(self):
        rows = [show(2, "Same Show", "Same Show", 2024, 12, 100)]
        best, _ = self.pick(rows, "Same Show", 12, 1)
        self.assertIsNone(best)

    def test_near_future_season_within_slack_is_accepted(self):
        rows = [show(2, "Same Show", "Same Show", 1975, 51, 100)]
        best, _ = self.pick(rows, "Same Show", 52, 1)
        self.assertEqual(best["id"], 2)


class FixerTests(unittest.TestCase):
    def make(self, rows, replacement, enabled=True):
        calls = []

        def collect(name):
            calls.append(("collect", name))
            return rows

        def recognize(cid, source_title):
            calls.append(("recognize", cid, source_title))
            return replacement

        fixer = SeasonIdentityFixer(collect_candidates=collect,
                                    recognize_by_id=recognize,
                                    enabled=enabled, current_year=2026)
        return fixer, calls

    def test_repairs_and_caches_within_one_round(self):
        fixed = media(4775, 2007, 19, "真的不骗你")
        fixer, calls = self.make(WILTY, fixed)
        wrong = media(158196, 2022, 1)
        result = fixer.repair(wrong, names=["Would I Lie To You"], season=9,
                              query_title="Would I Lie To You S09 1080p")
        self.assertIs(result, fixed)
        again = fixer.repair(wrong, names=["Would I Lie To You"], season=9,
                             query_title="Would I Lie To You S09 1080p")
        self.assertIs(again, fixed)
        self.assertEqual(len([c for c in calls if c[0] == "collect"]), 1)
        self.assertEqual(calls[1], ("recognize", 4775,
                                    "Would I Lie To You S09 1080p"))
        self.assertEqual(fixer.stats, {"suspect": 2, "fixed": 1, "skipped": 0})

    def test_does_not_block_when_no_candidate(self):
        fixer, calls = self.make([], None)
        wrong = media(135657, 2021, 1)
        self.assertIs(fixer.repair(wrong, names=["废柴的一日三餐"], season=9),
                      wrong)
        self.assertEqual(fixer.stats["skipped"], 1)
        self.assertEqual([c for c in calls if c[0] == "recognize"], [])

    def test_remote_failure_keeps_original_identity(self):
        def boom(name):
            raise RuntimeError("TMDB down")

        fixer = SeasonIdentityFixer(collect_candidates=boom,
                                    recognize_by_id=lambda *_: None,
                                    current_year=2026)
        wrong = media(158196, 2022, 1)
        self.assertIs(fixer.repair(wrong, names=["Would I Lie To You"], season=9),
                      wrong)

    def test_rerecognized_show_with_too_few_seasons_is_rejected(self):
        fixer, _ = self.make(WILTY, media(4775, 2007, 1))
        wrong = media(158196, 2022, 1)
        self.assertIs(fixer.repair(wrong, names=["Would I Lie To You"], season=9),
                      wrong)

    def test_disabled_or_movie_is_untouched(self):
        fixer, calls = self.make(WILTY, media(4775, 2007, 19), enabled=False)
        wrong = media(158196, 2022, 1)
        self.assertIs(fixer.repair(wrong, names=["Would I Lie To You"], season=9),
                      wrong)
        self.assertIs(fixer.repair(wrong, names=["Would I Lie To You"], season=9,
                                   is_tv=False), wrong)
        self.assertEqual(calls, [])

    def test_falls_back_to_alternate_search_name(self):
        calls = []

        def collect(name):
            calls.append(name)
            return WILTY if normalize_name(name) == normalize_name("Would I Lie To You") else []

        fixer = SeasonIdentityFixer(
            collect_candidates=collect,
            recognize_by_id=lambda cid, _: media(4775, 2007, 19),
            current_year=2026)
        wrong = media(158196, 2022, 1)
        result = fixer.repair(
            wrong, names=["无关名称", "Would I Lie To You"], season=9)
        self.assertEqual(result.tmdb_id, 4775)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
