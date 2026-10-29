"""Tests for scoring and allocation logic."""

from django.test import SimpleTestCase

from moondistribution.distribution import allocate_moons, normalize_scores, rank_corporations
from moondistribution.forms import parse_wishlist


class _Moon:
    """Minimal moon stand-in for parse_wishlist."""

    def __init__(self, pk, name):
        self.pk, self.name = pk, name


class TestNormalizeScores(SimpleTestCase):
    """normalize_scores()"""

    weights = {"mining": 40, "pvp": 30, "members": 15, "fleet": 15}

    def test_best_corp_gets_100(self):
        """A corp that is best in every criterion gets a total of 100."""
        raw = {
            1: {"mining": 1000, "pvp": 50, "members": 20, "fleet": 30},
            2: {"mining": 500, "pvp": 25, "members": 10, "fleet": 15},
        }
        res = normalize_scores(raw, self.weights)
        self.assertEqual(res[1]["total"], 100.0)
        self.assertEqual(res[2]["total"], 50.0)

    def test_zero_weight_ignores_criterion(self):
        """Weight 0 must not be replaced by a default (null-check bug from the Node app)."""
        raw = {1: {"mining": 0, "pvp": 100, "members": 0, "fleet": 0},
               2: {"mining": 100, "pvp": 0, "members": 0, "fleet": 0}}
        res = normalize_scores(raw, {"mining": 1, "pvp": 0, "members": 0, "fleet": 0})
        self.assertEqual(res[1]["total"], 0.0)
        self.assertEqual(res[2]["total"], 100.0)

    def test_all_zero_values(self):
        """No activity at all must not divide by zero."""
        raw = {1: {"mining": 0, "pvp": 0, "members": 0, "fleet": 0}}
        self.assertEqual(normalize_scores(raw, self.weights)[1]["total"], 0.0)

    def test_per_member(self):
        """Per-member mode: small active corp can beat a big one."""
        raw = {
            1: {"mining": 1000, "pvp": 0, "members": 100, "fleet": 0},  # 10 per member
            2: {"mining": 500, "pvp": 0, "members": 10, "fleet": 0},    # 50 per member
        }
        res = normalize_scores(raw, {"mining": 1, "pvp": 0, "members": 0, "fleet": 0}, per_member=True)
        self.assertGreater(res[2]["total"], res[1]["total"])


class TestRanking(SimpleTestCase):
    """rank_corporations()"""

    def test_tie_goes_to_earlier_application(self):
        """Equal score → whoever applied first ranks higher."""
        scores = {1: {"total": 50}, 2: {"total": 50}, 3: {"total": 80}}
        self.assertEqual(rank_corporations(scores, [2, 1, 3]), [3, 2, 1])


class TestAllocation(SimpleTestCase):
    """allocate_moons()"""

    def test_draft_order(self):
        """Best corp picks first, but each corp gets one moon per pass."""
        wishes = {
            "A": [(1, 10), (2, 11), (3, 12)],
            "B": [(1, 10), (2, 11)],
            "C": [(1, 11)],
        }
        picks = allocate_moons(["A", "B", "C"], wishes, max_per_corp=3)
        result = {p["moon"]: p["corp"] for p in picks}
        self.assertEqual(result[10], "A")   # A first wish
        self.assertEqual(result[11], "B")   # B falls back to its 2nd wish
        self.assertEqual(result[12], "A")   # 2nd pass: A gets its 3rd wish
        self.assertEqual(len(picks), 3)     # C gets nothing (11 is gone)

    def test_max_per_corp(self):
        """A corp never gets more than max_per_corp moons."""
        wishes = {"A": [(1, 1), (2, 2), (3, 3)]}
        picks = allocate_moons(["A"], wishes, max_per_corp=2)
        self.assertEqual(len(picks), 2)

    def test_priority_order_respected(self):
        """Wishes are served by priority, not by list order."""
        picks = allocate_moons(["A"], {"A": [(2, 99), (1, 42)]}, max_per_corp=1)
        self.assertEqual(picks[0]["moon"], 42)
        self.assertEqual(picks[0]["priority"], 1)


class TestParseWishlist(SimpleTestCase):
    """parse_wishlist()"""

    moons = [_Moon(1, "M1"), _Moon(2, "M2"), _Moon(3, "M3")]

    def test_gaps_are_renumbered(self):
        """Priorities 3 and 7 become 1 and 2."""
        wishes, errors = parse_wishlist({"prio_1": "7", "prio_3": "3"}, self.moons, 10)
        self.assertEqual(errors, [])
        self.assertEqual([(p, m.pk) for p, m in wishes], [(1, 3), (2, 1)])

    def test_duplicate_priority(self):
        """Same priority twice is rejected."""
        _w, errors = parse_wishlist({"prio_1": "1", "prio_2": "1"}, self.moons, 10)
        self.assertTrue(errors)

    def test_too_many(self):
        """More wishes than allowed are rejected."""
        _w, errors = parse_wishlist({"prio_1": "1", "prio_2": "2", "prio_3": "3"}, self.moons, 2)
        self.assertTrue(errors)

    def test_empty(self):
        """At least one moon is required."""
        _w, errors = parse_wishlist({}, self.moons, 10)
        self.assertTrue(errors)
