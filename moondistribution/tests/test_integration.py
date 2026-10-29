"""Integration tests: data collection from AA/Corptools, full distribution run and views."""

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter, EveCorporationInfo

from moondistribution.models import Application, ApplicationWish, DistributionSettings, Moon, Round, RoundBonus
from moondistribution.providers import collect_members, collect_mining, eligible_corporations_for
from moondistribution.tasks import distribute_round, process_rounds

ALLIANCE_ID = 99000001


def _make_user(name, char_id, corp, perms=("basic_access",)):
    """User with one main character in the given corp and the given app permissions."""
    user = User.objects.create_user(name)
    char = EveCharacter.objects.create(
        character_id=char_id, character_name=name, corporation_id=corp.corporation_id,
        corporation_name=corp.corporation_name, corporation_ticker=corp.corporation_ticker,
        alliance_id=ALLIANCE_ID, alliance_name="Test Alliance", alliance_ticker="TST",
    )
    CharacterOwnership.objects.create(user=user, character=char, owner_hash=f"hash{char_id}")
    user.profile.main_character = char
    user.profile.save()
    for p in perms:
        user.user_permissions.add(Permission.objects.get(codename=p, content_type__app_label="moondistribution"))
    return User.objects.get(pk=user.pk), char


class IntegrationBase(TestCase):
    """Shared fixtures: alliance with two corps, CEOs, an officer, mining data and moons."""

    @classmethod
    def setUpTestData(cls):
        """Alliance with two corps, a CEO each, some mining and a moon pool."""
        alliance = EveAllianceInfo.objects.create(
            alliance_id=ALLIANCE_ID, alliance_name="Test Alliance", alliance_ticker="TST", executor_corp_id=1001,
        )
        cls.corp_a = EveCorporationInfo.objects.create(
            corporation_id=1001, corporation_name="Alpha Corp", corporation_ticker="ALPHA",
            member_count=10, alliance=alliance, ceo_id=5001,
        )
        cls.corp_b = EveCorporationInfo.objects.create(
            corporation_id=1002, corporation_name="Bravo Corp", corporation_ticker="BRAVO",
            member_count=10, alliance=alliance, ceo_id=5002,
        )
        settings = DistributionSettings.get_solo()
        settings.alliance_id = ALLIANCE_ID
        settings.weight_pvp = 0  # no zKill in tests unless mocked
        settings.save()

        cls.ceo_a, cls.char_a = _make_user("ceo_a", 5001, cls.corp_a)
        cls.ceo_b, cls.char_b = _make_user("ceo_b", 5002, cls.corp_b)
        cls.member_b, _c = _make_user("member_b", 5003, cls.corp_b)
        cls.officer, _c = _make_user("officer", 5004, cls.corp_a, perms=("basic_access", "mining_officer"))

        # Mining: Alpha mined a lot more
        from corptools.models import CharacterAudit, CharacterMiningLedger
        from eve_sde.models import ItemType, SolarSystem

        ore = ItemType.objects.create(id=45513, name="Bitumens", volume=10.0)
        system = SolarSystem.objects.create(id=30000001, name="R-ARKN")
        audit_a = CharacterAudit.objects.create(character=cls.char_a, last_known_login=timezone.now())
        audit_b = CharacterAudit.objects.create(character=cls.char_b, last_known_login=timezone.now())
        today = timezone.now().date()
        CharacterMiningLedger.objects.create(id="a1", character=audit_a, date=today, type_name=ore, system=system, quantity=1000)
        CharacterMiningLedger.objects.create(id="b1", character=audit_b, date=today, type_name=ore, system=system, quantity=100)
        # Outside the window – must not count
        CharacterMiningLedger.objects.create(
            id="b2", character=audit_b, date=today - timedelta(days=400), type_name=ore, system=system, quantity=99999,
        )

        cls.moon1 = Moon.objects.create(name="R-ARKN I - Moon 1", rarity="R32")
        cls.moon2 = Moon.objects.create(name="R-ARKN II - Moon 1", rarity="R16")
        cls.moon_r64 = Moon.objects.create(name="R-ARKN III - Moon 1", rarity="R64")

    def _round(self, status=Round.Status.OPEN, ended=False):
        """Round with both moons; open now or already ended."""
        now = timezone.now()
        end = now - timedelta(minutes=1) if ended else now + timedelta(days=7)
        r = Round.objects.create(
            name="H1", application_start=now - timedelta(days=7), application_end=end,
            evaluation_start=date.today() - timedelta(days=182), evaluation_end=date.today(), status=status,
        )
        r.moons.set([self.moon1, self.moon2])
        return r



class DistributionIntegrationTest(IntegrationBase):
    """End-to-end: two corps apply, activity decides who gets the contested moon."""

    def test_eligibility(self):
        """CEOs see their own corp, members nothing, officers all alliance corps."""
        self.assertEqual(list(eligible_corporations_for(self.ceo_a)), [self.corp_a])
        self.assertEqual(list(eligible_corporations_for(self.member_b)), [])
        self.assertEqual(eligible_corporations_for(self.officer).count(), 2)
        self.assertEqual(list(eligible_corporations_for(self.officer, include_officer=False)), [])

    def test_collectors(self):
        """Members by main corp, mining volume in m³ inside the window only."""
        members = collect_members([1001, 1002], 30)
        self.assertEqual(members[1002]["total"], 2)
        self.assertEqual(members[1002]["active"], 1)
        mining = collect_mining([1001, 1002], date.today() - timedelta(days=182), date.today())
        self.assertEqual(mining[1001], 10000.0)
        self.assertEqual(mining[1002], 1000.0)

    def test_full_distribution(self):
        """Both want moon1 first – Alpha mined more and wins it, Bravo gets moon2."""
        r = self._round(ended=True)
        for corp, user in ((self.corp_a, self.ceo_a), (self.corp_b, self.ceo_b)):
            app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
            ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
            ApplicationWish.objects.create(application=app, moon=self.moon2, priority=2)

        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round):
            process_rounds()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE, r.last_error)
        result = {a.moon_id: a.corporation_id for a in r.allocations.all()}
        self.assertEqual(result[self.moon1.pk], self.corp_a.pk)
        self.assertEqual(result[self.moon2.pk], self.corp_b.pk)
        self.assertEqual(r.scores.get(rank=1).corporation, self.corp_a)
        # Results page renders with ranking and allocation
        self.client.force_login(self.ceo_b)
        resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        self.assertContains(resp, "Alpha Corp")
        self.assertContains(resp, "10,000")

    def test_zkill_down_still_distributes(self):
        """zKillboard errors don't stop the round – PvP = 0 and a warning."""
        settings = DistributionSettings.get_solo()
        settings.weight_pvp = 30
        settings.save()
        r = self._round(ended=True)
        app = Application.objects.create(round=r, corporation=self.corp_a, submitted_by=self.ceo_a)
        ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
        import requests

        with mock.patch("moondistribution.providers.requests.get", side_effect=requests.ConnectionError("down")), \
                mock.patch.object(distribute_round, "delay", side_effect=distribute_round):
            process_rounds()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE)
        self.assertIn("zKillboard", r.last_error)

    def test_apply_view(self):
        """CEO applies via the form, priorities are stored renumbered."""
        r = self._round()
        self.client.force_login(self.ceo_a)
        url = reverse("moondistribution:apply", args=[r.pk, self.corp_a.corporation_id])
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {f"prio_{self.moon2.pk}": "5", f"prio_{self.moon1.pk}": "9", "comment": "pls"})
        self.assertEqual(resp.status_code, 302)
        wishes = list(Application.objects.get(round=r).wishes.values_list("moon_id", "priority"))
        self.assertEqual(wishes, [(self.moon2.pk, 1), (self.moon1.pk, 2)])

    def test_apply_forbidden_for_other_corp(self):
        """A CEO can't apply for another corp."""
        r = self._round()
        self.client.force_login(self.ceo_a)
        resp = self.client.get(reverse("moondistribution:apply", args=[r.pk, self.corp_b.corporation_id]))
        self.assertEqual(resp.status_code, 404)

    def test_pages_render(self):
        """All pages render for an officer; members get 403 on officer pages."""
        r = self._round()
        self.client.force_login(self.officer)
        for name, args in (("index", []), ("round_detail", [r.pk]), ("round_create", []), ("round_edit", [r.pk]),
                           ("moons", []), ("moon_add", []), ("moon_edit", [self.moon1.pk]), ("settings", [])):
            resp = self.client.get(reverse(f"moondistribution:{name}", args=args))
            self.assertEqual(resp.status_code, 200, name)
        self.client.force_login(self.member_b)
        self.assertEqual(self.client.get(reverse("moondistribution:index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("moondistribution:settings")).status_code, 403)

    def test_round_create_view(self):
        """Officer creates a round, it starts as draft with the chosen moons."""
        self.client.force_login(self.officer)
        now = timezone.now()
        resp = self.client.post(reverse("moondistribution:round_create"), {
            "name": "H2", "description": "",
            "evaluation_start": "2026-05-01", "evaluation_end": "2026-10-31",
            "moons": [self.moon1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        r = Round.objects.get(name="H2")
        self.assertEqual(r.status, Round.Status.DRAFT)
        self.assertEqual(list(r.moons.all()), [self.moon1])
        self.assertIsNone(r.application_end)

        # Opening starts the application week
        self.client.post(reverse("moondistribution:round_open", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.OPEN)
        self.assertAlmostEqual((r.application_end - now).total_seconds(), 7 * 86400, delta=120)
        self.assertTrue(r.is_open)

    def test_distribution_runs_only_once(self):
        """After the week the round is distributed exactly once; later beat runs do nothing."""
        r = self._round(ended=True)
        app = Application.objects.create(round=r, corporation=self.corp_a, submitted_by=self.ceo_a)
        ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round) as delay, \
                mock.patch("moondistribution.distribution.notify") as notify:
            process_rounds()
            process_rounds()
            process_rounds()
        self.assertEqual(delay.call_count, 1)
        self.assertEqual(notify.call_count, 1)
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE)

    def test_open_round_not_distributed_before_end(self):
        """A round whose week is not over yet is left alone."""
        r = self._round()
        with mock.patch.object(distribute_round, "delay") as delay:
            process_rounds()
        delay.assert_not_called()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.OPEN)

    def test_failed_distribution_is_not_retried(self):
        """A failed run keeps the error and is not picked up again by the beat task."""
        r = self._round(ended=True)
        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round) as delay, \
                mock.patch("moondistribution.tasks.run_distribution", side_effect=RuntimeError("boom")):
            process_rounds()
            process_rounds()
        self.assertEqual(delay.call_count, 1)
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.CLOSED)
        self.assertIn("boom", r.last_error)


class FairnessIntegrationTest(IntegrationBase):
    """Bonuses and R64 exclusion end-to-end (reuses the fixtures above)."""

    def _distribute(self, r):
        """Run the automatic distribution for a round synchronously."""
        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round), \
                mock.patch("moondistribution.distribution.notify"):
            process_rounds()
        r.refresh_from_db()
        return r

    def _apply(self, r, corp, user, moons):
        """Application with the given moons in priority order."""
        app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
        for prio, moon in enumerate(moons, start=1):
            ApplicationWish.objects.create(application=app, moon=moon, priority=prio)

    def test_manual_bonus_turns_the_ranking(self):
        """Bravo mined less, but a manual bonus of +100 puts it first."""
        r = self._round(ended=True)
        self._apply(r, self.corp_a, self.ceo_a, [self.moon2, self.moon1])
        self._apply(r, self.corp_b, self.ceo_b, [self.moon2, self.moon1])
        RoundBonus.objects.create(round=r, corporation=self.corp_b, points=100, reason="little last time")
        r = self._distribute(r)
        top = r.scores.get(rank=1)
        self.assertEqual(top.corporation, self.corp_b)
        self.assertEqual(top.bonus_manual, 100)
        self.assertEqual(r.allocations.get(moon=self.moon2).corporation, self.corp_b)

    def test_compensation_from_previous_round(self):
        """Corp that got nothing last round receives the automatic bonus this round."""
        first = self._round(ended=True)
        self._apply(first, self.corp_a, self.ceo_a, [self.moon2])
        self._apply(first, self.corp_b, self.ceo_b, [self.moon2])
        self._distribute(first)  # Alpha wins, Bravo gets nothing

        second = self._round(ended=True)
        self._apply(second, self.corp_b, self.ceo_b, [self.moon2])
        second = self._distribute(second)
        self.assertEqual(second.scores.get(corporation=self.corp_b).bonus_auto, 15)

    def test_r64_excluded(self):
        """R64 moons are never allocated and can't be wished when excluded."""
        r = self._round(ended=True)
        r.moons.add(self.moon_r64)
        self._apply(r, self.corp_a, self.ceo_a, [self.moon_r64, self.moon2])
        r = self._distribute(r)
        self.assertEqual(list(r.allocations.values_list("moon_id", flat=True)), [self.moon2.pk])
        # and the round form does not offer R64 at all
        from moondistribution.forms import RoundForm
        self.assertNotIn(self.moon_r64, RoundForm().fields["moons"].queryset)

    def test_bonus_view(self):
        """Officer can add a bonus via the round page."""
        r = self._round()
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("moondistribution:bonus_save", args=[r.pk]), {
            "corporation": self.corp_b.pk, "points": 20, "reason": "small corp",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RoundBonus.objects.get(round=r).points, 20)


class RarityIntegrationTest(IntegrationBase):
    """Rarity import and bulk edit on the moons page."""

    def test_paste_import_fills_only_missing(self):
        """Scan paste fills empty rarities; existing ones stay unless overwrite is ticked."""
        empty = Moon.objects.create(name="X-1 I - Moon 1")
        self.client.force_login(self.officer)
        paste = f"{empty.name}\n\tZircon\t0.3\n{self.moon2.name}\n\tBitumens\t0.5\nUnknown - Moon 9\n\tZircon\t0.1\n"
        self.client.post(reverse("moondistribution:moon_rarity_import"), {"paste": paste, "source": "paste"})
        empty.refresh_from_db()
        self.moon2.refresh_from_db()
        self.assertEqual(empty.rarity, "R32")
        self.assertEqual(self.moon2.rarity, "R16")  # not overwritten
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "overwrite": "on"})
        self.moon2.refresh_from_db()
        self.assertEqual(self.moon2.rarity, "R4")

    def test_bulk_set_rarity(self):
        """Ticked moons get the chosen rarity in one go."""
        a = Moon.objects.create(name="Y I - Moon 1")
        b = Moon.objects.create(name="Y I - Moon 2")
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("moondistribution:moon_bulk"), {
            "moon_ids": [a.pk, b.pk], "action": "R8", "next": "https://evil.example.com/",
        })
        self.assertEqual(resp.url, reverse("moondistribution:moons"))  # no open redirect
        self.assertEqual(set(Moon.objects.filter(rarity="R8").values_list("pk", flat=True)), {a.pk, b.pk})

    def test_moons_page_filters(self):
        """Filter 'no rarity' and search render."""
        self.client.force_login(self.officer)
        for params in ({"rarity": "missing"}, {"rarity": "R32"}, {"q": "ARKN"}):
            self.assertEqual(self.client.get(reverse("moondistribution:moons"), params).status_code, 200)

    def test_paste_creates_missing_moons(self):
        """With 'create' ticked, unknown moons from the paste are added with system and rarity."""
        self.client.force_login(self.officer)
        paste = "Old Man Star VII - Moon 2\n\tZircon\t0.3\nJ5A-IX II - Moon 1; R8\n"
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "create": "on"})
        a = Moon.objects.get(name="Old Man Star VII - Moon 2")
        b = Moon.objects.get(name="J5A-IX II - Moon 1")
        self.assertEqual((a.system_name, a.rarity), ("Old Man Star", "R32"))
        self.assertEqual((b.system_name, b.rarity), ("J5A-IX", "R8"))
        # a second paste does not duplicate
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "create": "on"})
        self.assertEqual(Moon.objects.filter(name="J5A-IX II - Moon 1").count(), 1)

    def test_sheet_paste_creates_moons_with_note(self):
        """Pasting sheet rows creates the moons with EVE name, system, rarity and % note."""
        self.client.force_login(self.officer)
        paste = "system\tPlant\tMoon\tType\t%\tsum\n02V-BK\t6\t15\tR32\t28\t1\n"
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "create": "on"})
        moon = Moon.objects.get(name="02V-BK VI - Moon 15")
        self.assertEqual((moon.system_name, moon.rarity, moon.notes), ("02V-BK", "R32", "28 %"))

    def test_composition_is_stored_and_shown(self):
        """Fey-style row stores the ores; moons page and apply page show them."""
        self.client.force_login(self.officer)
        paste = "R32\tD6SK-L\t4\t1\tZircon\t17.5%\tBitumens\t41.5%\n"
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "create": "on"})
        moon = Moon.objects.get(name="D6SK-L IV - Moon 1")
        self.assertEqual(moon.composition, [{"ore": "Zircon", "percent": 17.5}, {"ore": "Bitumens", "percent": 41.5}])
        self.assertContains(self.client.get(reverse("moondistribution:moons")), "Zircon 17.5%")

    def test_wish_counts_for_officer(self):
        """Officers see how many corps want each moon."""
        now = timezone.now()
        r = Round.objects.create(
            name="H9", application_start=now - timedelta(days=1), application_end=now + timedelta(days=6),
            evaluation_start=date.today() - timedelta(days=182), evaluation_end=date.today(), status=Round.Status.OPEN,
        )
        r.moons.set([self.moon1, self.moon2])
        for corp, user in ((self.corp_a, self.ceo_a), (self.corp_b, self.ceo_b)):
            app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
            ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        rows = {row["moon"].pk: row["wishes"] for row in resp.context["moons"]}
        self.assertEqual(rows, {self.moon1.pk: 2, self.moon2.pk: 0})



class RegionTest(IntegrationBase):
    """Region from the EVE map data and region tabs."""

    @classmethod
    def setUpTestData(cls):
        """Two regions with one system each in the SDE tables."""
        super().setUpTestData()
        from eve_sde.models import Constellation, Region, SolarSystem

        for rid, region, cid, system in ((10000039, "Esoteria", 20000450, "02V-BK"),
                                         (10000056, "Feythabolis", 20000650, "D6SK-L")):
            r = Region.objects.create(id=rid, name=region)
            c = Constellation.objects.create(id=cid, name=f"C-{region}", region=r)
            SolarSystem.objects.create(id=cid * 10, name=system, constellation=c)

    def test_region_set_on_import(self):
        """Pasted moons get their region; unknown systems stay empty ('Other')."""
        self.client.force_login(self.officer)
        paste = "02V-BK\t6\t15\tR32\t28\nR32\tD6SK-L\t4\t1\tZircon\t17.5%\nNOWHERE\t1\t1\tR8\t10\n"
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "create": "on"})
        regions = dict(Moon.objects.filter(name__in=[
            "02V-BK VI - Moon 15", "D6SK-L IV - Moon 1", "NOWHERE I - Moon 1",
        ]).values_list("name", "region_name"))
        self.assertEqual(regions, {
            "02V-BK VI - Moon 15": "Esoteria", "D6SK-L IV - Moon 1": "Feythabolis", "NOWHERE I - Moon 1": "",
        })

    def test_region_tabs_render(self):
        """Apply page, round page, round form and moon list show one tab per region."""
        a = Moon.objects.create(name="02V-BK VI - Moon 15", system_name="02V-BK", region_name="Esoteria", rarity="R32")
        b = Moon.objects.create(name="D6SK-L IV - Moon 1", system_name="D6SK-L", region_name="Feythabolis", rarity="R16")
        now = timezone.now()
        r = Round.objects.create(
            name="H3", application_start=now - timedelta(days=1), application_end=now + timedelta(days=6),
            evaluation_start=date.today() - timedelta(days=182), evaluation_end=date.today(), status=Round.Status.OPEN,
        )
        r.moons.set([a, b])
        self.client.force_login(self.officer)
        pages = [
            reverse("moondistribution:apply", args=[r.pk, self.corp_a.corporation_id]),
            reverse("moondistribution:round_detail", args=[r.pk]),
            reverse("moondistribution:round_edit", args=[r.pk]),
            reverse("moondistribution:moons"),
        ]
        for url in pages:
            resp = self.client.get(url)
            self.assertContains(resp, "Esoteria")
            self.assertContains(resp, "Feythabolis")
        self.assertContains(self.client.get(reverse("moondistribution:moons"), {"region": "Esoteria"}), a.name)
        self.assertNotContains(self.client.get(reverse("moondistribution:moons"), {"region": "Esoteria"}), b.name)
