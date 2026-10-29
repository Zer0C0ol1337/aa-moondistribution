"""Tests for scoring and allocation logic."""

from django.test import SimpleTestCase

from moondistribution.distribution import allocate_moons, compensation_bonus, normalize_scores, rank_corporations


class _Moon:
    """Minimal moon stand-in for parse_wishlist."""

    def __init__(self, pk, name):
        self.pk, self.name = pk, name


class TestNormalizeScores(SimpleTestCase):
    """normalize_scores()"""

    weights = {"pvp": 50, "members": 10, "fleet": 40}

    def test_best_corp_gets_100(self):
        """A corp that is best in every criterion gets a total of 100."""
        raw = {
            1: {"pvp": 50, "members": 20, "fleet": 30},
            2: {"pvp": 25, "members": 10, "fleet": 15},
        }
        res = normalize_scores(raw, self.weights)
        self.assertEqual(res[1]["total"], 100.0)
        self.assertEqual(res[2]["total"], 50.0)

    def test_zero_weight_ignores_criterion(self):
        """Weight 0 must not be replaced by a default (null-check bug from the Node app)."""
        raw = {1: {"pvp": 0, "members": 0, "fleet": 100},
               2: {"pvp": 100, "members": 0, "fleet": 0}}
        res = normalize_scores(raw, {"pvp": 1, "members": 0, "fleet": 0})
        self.assertEqual(res[1]["total"], 0.0)
        self.assertEqual(res[2]["total"], 100.0)

    def test_all_zero_values(self):
        """No activity at all must not divide by zero."""
        raw = {1: {"pvp": 0, "members": 0, "fleet": 0}}
        self.assertEqual(normalize_scores(raw, self.weights)[1]["total"], 0.0)

    def test_per_member(self):
        """Per-member mode: small active corp can beat a big one."""
        raw = {
            1: {"pvp": 0, "members": 100, "fleet": 1000},  # 10 per member
            2: {"pvp": 0, "members": 10, "fleet": 500},    # 50 per member
        }
        res = normalize_scores(raw, {"pvp": 0, "members": 0, "fleet": 1}, per_member=True)
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


class TestEqualWishes(SimpleTestCase):
    """All wishes equal: a corp gets the best of its free moons."""

    def test_best_moon_first(self):
        """A gets its best moon (R32 59 %), B the best of the rest, then A the next one."""
        quality = {1: 4050.0, 2: 32059.9, 3: 16030.0, 4: 32020.0}
        wishes = {"A": [(1, m) for m in (1, 2, 3, 4)], "B": [(1, m) for m in (2, 4, 3)]}
        picks = allocate_moons(["A", "B"], wishes, max_per_corp=2, moon_quality=quality)
        self.assertEqual([(p["corp"], p["moon"]) for p in picks], [("A", 2), ("B", 4), ("A", 3)])


class TestRarityLimits(SimpleTestCase):
    """allocate_moons() with rarity limits."""

    def test_r32_limit_lets_next_corp_have_it(self):
        """Top corp wants two R32 but may only get one – the second R32 goes to the next corp."""
        rarity = {1: "R32", 2: "R32", 3: "R8"}
        wishes = {"A": [(1, 1), (2, 2), (3, 3)], "B": [(1, 1), (2, 2)]}
        picks = allocate_moons(["A", "B"], wishes, max_per_corp=3, moon_rarity=rarity, rarity_limits={"R32": 1})
        result = {p["moon"]: p["corp"] for p in picks}
        self.assertEqual(result[1], "A")
        self.assertEqual(result[2], "B")
        self.assertEqual(result[3], "A")  # A fills up with a lower moon

    def test_no_limit_when_not_configured(self):
        """Without a limit a corp can take several R32."""
        rarity = {1: "R32", 2: "R32"}
        picks = allocate_moons(["A"], {"A": [(1, 1), (2, 2)]}, max_per_corp=3, moon_rarity=rarity, rarity_limits={})
        self.assertEqual(len(picks), 2)


class TestCompensationBonus(SimpleTestCase):
    """compensation_bonus()"""

    def test_graded_bonus(self):
        """No moon → big bonus, moons but no R32 → small bonus, R32 or not applied → none."""
        previous = {1: [], 2: ["R8", "R4"], 3: ["R32"]}
        res = compensation_bonus([1, 2, 3, 4], previous, bonus_no_moon=15, bonus_no_r32=8)
        self.assertEqual(res, {1: 15, 2: 8, 3: 0, 4: 0})

    def test_no_previous_round(self):
        """First round ever: nobody gets a bonus."""
        self.assertEqual(compensation_bonus([1], None, 15, 8), {1: 0})

    def test_zero_disables(self):
        """Bonus 0 must stay 0 (no default fallback)."""
        self.assertEqual(compensation_bonus([1], {1: []}, 0, 0), {1: 0})


class TestParseSelection(SimpleTestCase):
    """parse_selection()"""

    moons = [_Moon(1, "M1"), _Moon(2, "M2"), _Moon(3, "M3")]

    def test_selection(self):
        """Ticked moons of the pool are returned, duplicates and foreign IDs ignored."""
        from moondistribution.forms import parse_selection

        chosen, errors = parse_selection([3, 1, 3, 99], self.moons, 10)
        self.assertEqual(errors, [])
        self.assertEqual([m.pk for m in chosen], [3, 1])

    def test_too_many(self):
        """More ticks than allowed are rejected."""
        from moondistribution.forms import parse_selection

        _c, errors = parse_selection([1, 2, 3], self.moons, 2)
        self.assertTrue(errors)

    def test_empty(self):
        """At least one moon is required."""
        from moondistribution.forms import parse_selection

        _c, errors = parse_selection([], self.moons, 10)
        self.assertTrue(errors)

class TestRarityPaste(SimpleTestCase):
    """parse_rarity_paste() / ore_rarity()"""

    def test_eve_scan_copy(self):
        """EVE moon scan copy: rarity = best ore of the moon, header ignored."""
        from moondistribution.rarity import parse_rarity_paste

        text = (
            "Moon\tMoon Product\tQuantity\tOre TypeID\tSolarSystemID\tPlanetID\tMoonID\n"
            "R-ARKN I - Moon 1\n"
            "\tBitumens\t0.42\t45492\t30000001\t40000001\t40000002\n"
            "\tZircon\t0.31\t45503\t30000001\t40000001\t40000002\n"
            "R-ARKN II - Moon 3\n"
            "\tSylvite\t0.5\t45491\t30000001\t40000003\t40000004\n"
            "R-ARKN III - Moon 2\n"
        )
        self.assertEqual(parse_rarity_paste(text), {"R-ARKN I - Moon 1": "R32", "R-ARKN II - Moon 3": "R4"})

    def test_simple_list(self):
        """'moon; R16', tab and comma separated lines."""
        from moondistribution.rarity import parse_rarity_paste

        text = "A - Moon 1; R16\nB - Moon 2\tR 8\nC - Moon 3, r64\n"
        self.assertEqual(parse_rarity_paste(text), {"A - Moon 1": "R16", "B - Moon 2": "R8", "C - Moon 3": "R64"})

    def test_ore_variants(self):
        """Ore variants count like the base ore."""
        from moondistribution.rarity import ore_rarity

        self.assertEqual(ore_rarity("Glistening Zircon"), "R32")
        self.assertEqual(ore_rarity("Brimful Bitumens"), "R4")
        self.assertEqual(ore_rarity("Veldspar"), "")


class TestSheetFormat(SimpleTestCase):
    """Rows copied from the alliance Google Sheet (system | planet | moon | type | % | sum)."""

    sheet = (
        "system\tPlant\tMoon\tType\t%\tsum\n"
        "29YH-V\t8\t2\tR64\t18\t1\n"
        "02V-BK\t6\t15\tR32\t28\t1\n"
        "P9F-ZG\t9\t20\tR32\t28\t0\n"
        "7P-J38\t10\t4\tR16\t35\t1\n"
        "A5MT-B\t7\t11\tR16\t0\t\n"
    )

    def test_names_and_rarity(self):
        """Planet number becomes a roman numeral like in EVE; 'sum' is ignored."""
        from moondistribution.rarity import parse_rarity_paste

        self.assertEqual(parse_rarity_paste(self.sheet), {
            "29YH-V VIII - Moon 2": "R64",
            "02V-BK VI - Moon 15": "R32",
            "P9F-ZG IX - Moon 20": "R32",
            "7P-J38 X - Moon 4": "R16",
            "A5MT-B VII - Moon 11": "R16",
        })

    def test_percent_as_note(self):
        """The % column is used as moon note."""
        from moondistribution.rarity import parse_paste

        entries = parse_paste(self.sheet)
        self.assertEqual(entries["02V-BK VI - Moon 15"]["note"], "28 %")
        self.assertEqual(entries["A5MT-B VII - Moon 11"]["note"], "0 %")

    def test_fey_layout(self):
        """Fey sheet: Category | System | Planet | Moon | Mineral/% × 4 | SUM."""
        from moondistribution.rarity import parse_paste

        text = (
            "Category\tSystem\tPlanet\tMoon\tMineral 1\t% 1\tMineral 2\t% 2\tMineral 3\t% 3\tMineral 4\t% 4\tSUM\n"
            "R64\tM-PGT0\t2\t4\tMonazite\t24.5%\tLoparite\t19.8%\tZircon\t24.5%\tChromite\t31.3%\t44,30%\n"
            "R16\tR97-CI\t6\t8\tSperrylite\t25.4%\tBitumens\t54.6%\t\t\t\t\t25,40%\n"
        )
        entries = parse_paste(text)
        moon = entries["M-PGT0 II - Moon 4"]
        self.assertEqual(moon["rarity"], "R64")
        self.assertEqual([c["ore"] for c in moon["composition"]], ["Monazite", "Loparite", "Zircon", "Chromite"])
        self.assertEqual(moon["composition"][3]["percent"], 31.3)
        self.assertEqual(entries["R97-CI VI - Moon 8"]["composition"],
                         [{"ore": "Sperrylite", "percent": 25.4}, {"ore": "Bitumens", "percent": 54.6}])

    def test_eso_layout(self):
        """ESO sheet: key | System | P | M | Ore/Density × 4 | Class – rarity from the best ore."""
        from moondistribution.rarity import parse_paste

        text = (
            "\tSystem\tP\tM\tOre 1\tDensity 1\tOre 2\tDensity 2\tOre 3\tDensity 3\tOre 4\tDensity 4\tClass\n"
            "29YH-V82\t29YH-V\t8\t2\tCoesite\t23%\tXenotime\t18%\tCobaltite\t9%\t\t\t64\tok\n"
            "G-JC9R417\tG-JC9R\t4\t17\tCinnabar\t23%\tcoesite\t28%\tBitumens\t8%\tSperrylite\t41%\t32\tok\n"
        )
        entries = parse_paste(text)
        self.assertEqual(entries["29YH-V VIII - Moon 2"]["rarity"], "R64")
        g = entries["G-JC9R IV - Moon 17"]
        self.assertEqual(g["rarity"], "R32")
        self.assertIn({"ore": "Coesite", "percent": 28.0}, g["composition"])

    def test_eve_scan_composition(self):
        """EVE scan copy: fractions become percent."""
        from moondistribution.rarity import parse_paste

        text = "R-ARKN I - Moon 1\n\tZircon\t0.31\t45503\n\tBitumens\t0.69\t45492\n"
        entry = parse_paste(text)["R-ARKN I - Moon 1"]
        self.assertEqual(entry["rarity"], "R32")
        self.assertEqual(entry["composition"], [{"ore": "Zircon", "percent": 31.0}, {"ore": "Bitumens", "percent": 69.0}])

    def test_roman(self):
        """Roman numerals for EVE planet numbers."""
        from moondistribution.rarity import to_roman

        self.assertEqual([to_roman(n) for n in (1, 4, 6, 9, 11, 14, 19)], ["I", "IV", "VI", "IX", "XI", "XIV", "XIX"])


class TestBestShare(SimpleTestCase):
    """Moon.best_share / rarity_sort without database."""

    def test_best_share_of_own_rarity(self):
        """The share of the best ore of the moon's own class counts, not the biggest ore overall."""
        from moondistribution.models import Moon

        moon = Moon(rarity="R32", composition=[
            {"ore": "Zircon", "percent": 17.5}, {"ore": "Bitumens", "percent": 41.5}, {"ore": "Cinnabar", "percent": 20.0},
        ])
        self.assertEqual(moon.best_share, 20.0)
        self.assertEqual(moon.rarity_sort, 32020.0)

    def test_note_fallback(self):
        """Simple sheet without ores: the '28 %' note is used."""
        from moondistribution.models import Moon

        self.assertEqual(Moon(rarity="R16", notes="28 %").best_share, 28.0)
        self.assertIsNone(Moon(rarity="R16").best_share)
