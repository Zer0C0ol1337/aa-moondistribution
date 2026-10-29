"""Integration tests: data collection from AA/Corptools, full distribution run and views."""

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter, EveCorporationInfo

from moondistribution.models import (
    Application, ApplicationWish, CorporationProbation, DistributionSettings, Moon, Round, RoundBonus, Sig, SigClaim,
)
from moondistribution.providers import collect_fleets, collect_members, eligible_corporations_for
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
    """Shared fixtures: alliance with two corps, CEOs, an officer, fleet data and moons."""

    @classmethod
    def setUpTestData(cls):
        """Alliance with two corps, a CEO each, some fleet activity and a moon pool."""
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

        # Logins (active members) from Corptools
        from corptools.models import CharacterAudit

        CharacterAudit.objects.create(character=cls.char_a, last_known_login=timezone.now())
        CharacterAudit.objects.create(character=cls.char_b, last_known_login=timezone.now())

        # Fleets (AA built-in FAT): Alpha flew 10 fleets, Bravo 2 (+1 outside the window that must not count)
        from allianceauth.fleetactivitytracking.models import Fat, Fatlink

        def _fats(user, char, count, when, prefix):
            for i in range(count):
                link = Fatlink.objects.create(
                    fleet=f"{prefix}{i}", hash=f"{prefix}{i}", duration=60, creator=user, fatdatetime=when,
                )
                Fat.objects.create(character=char, fatlink=link, system="R-ARKN", shiptype="Ferox",
                                   station="", user=user)

        _fats(cls.ceo_a, cls.char_a, 10, timezone.now(), "a")
        _fats(cls.ceo_b, cls.char_b, 2, timezone.now(), "b")
        _fats(cls.ceo_b, cls.char_b, 1, timezone.now() - timedelta(days=400), "old")

        cls.moon1 = Moon.objects.create(name="R-ARKN I - Moon 1", rarity="R32")
        cls.moon2 = Moon.objects.create(name="R-ARKN II - Moon 1", rarity="R16")
        cls.moon_r64 = Moon.objects.create(name="R-ARKN III - Moon 1", rarity="R64")

    def setUp(self):
        """Run the import tasks synchronously (no Celery worker in tests); no ESI – every corp joined long ago."""
        from moondistribution.tasks import import_moon_data, sync_moons, update_join_dates

        self.join_dates = {}  # corp_id → join date returned by the mocked ESI (default: 2 years ago)
        esi = mock.patch(
            "moondistribution.probation.fetch_join_date",
            side_effect=lambda cid, aid: self.join_dates.get(cid, timezone.now() - timedelta(days=730)),
        )
        self.esi_mock = esi.start()
        self.addCleanup(esi.stop)
        for task in (import_moon_data, sync_moons, update_join_dates):
            patcher = mock.patch.object(task, "delay", side_effect=task)
            patcher.start()
            self.addCleanup(patcher.stop)

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
        """Members by main corp, fleet participations inside the window only."""
        members = collect_members([1001, 1002], 30)
        self.assertEqual(members[1002]["total"], 2)
        self.assertEqual(members[1002]["active"], 1)
        # Activity rate: 1 of 10 characters (EVE member count) logged in recently
        self.assertEqual(members[1002]["ingame"], 10)
        self.assertEqual(members[1002]["chars_active"], 1)
        self.assertEqual(members[1002]["rate"], 10.0)
        fleets = collect_fleets([1001, 1002], date.today() - timedelta(days=182), date.today())
        self.assertEqual(fleets, {1001: 10, 1002: 2})

    def test_full_distribution(self):
        """Both want moon1 first – Alpha flew more fleets and wins it, Bravo gets moon2."""
        r = self._round(ended=True)
        for corp, user in ((self.corp_a, self.ceo_a), (self.corp_b, self.ceo_b)):
            app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
            ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
            ApplicationWish.objects.create(application=app, moon=self.moon2, priority=1)

        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round):
            process_rounds()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE, r.last_error)
        result = {a.moon_id: a.corporation_id for a in r.allocations.all()}
        self.assertEqual(result[self.moon1.pk], self.corp_a.pk)
        self.assertEqual(result[self.moon2.pk], self.corp_b.pk)
        self.assertEqual(r.scores.get(rank=1).corporation, self.corp_a)
        self.assertEqual(r.scores.get(rank=1).activity_rate, 10.0)
        self.assertEqual(r.scores.get(rank=1).members_ingame, 10)
        # Results page renders with ranking and allocation
        self.client.force_login(self.ceo_b)
        resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        self.assertContains(resp, "Alpha Corp")
        self.assertNotContains(resp, "Mining")

    def test_live_member_numbers_on_open_round(self):
        """While a round is open, officers see EVE members, Auth members, active players and the rate."""
        r = self._round()
        Application.objects.create(round=r, corporation=self.corp_b, submitted_by=self.ceo_b)
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        self.assertContains(resp, "10 members in EVE")
        self.assertContains(resp, "(1 / 10)")

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
        """CEO ticks moons, all are stored as equal wishes."""
        r = self._round()
        self.client.force_login(self.ceo_a)
        url = reverse("moondistribution:apply", args=[r.pk, self.corp_a.corporation_id])
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {"moon_ids": f"{self.moon2.pk},{self.moon1.pk}", "comment": "pls"})
        self.assertEqual(resp.status_code, 302)
        wishes = set(Application.objects.get(round=r).wishes.values_list("moon_id", "priority"))
        self.assertEqual(wishes, {(self.moon2.pk, 1), (self.moon1.pk, 1)})

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
                           ("moons", []), ("moon_add", []), ("moon_edit", [self.moon1.pk]), ("settings", []),
                           ("corps", [])):
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
            "moon_ids": f"{self.moon1.pk}",
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
        """Application with the given moons, all wanted equally."""
        app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
        for moon in moons:
            ApplicationWish.objects.create(application=app, moon=moon, priority=1)

    def test_manual_bonus_turns_the_ranking(self):
        """Bravo flew fewer fleets, but a manual bonus of +100 puts it first."""
        r = self._round(ended=True)
        self._apply(r, self.corp_a, self.ceo_a, [self.moon2, self.moon1])
        self._apply(r, self.corp_b, self.ceo_b, [self.moon2, self.moon1])
        RoundBonus.objects.create(round=r, corporation=self.corp_b, points=100, reason="little last time")
        r = self._distribute(r)
        top = r.scores.get(rank=1)
        self.assertEqual(top.corporation, self.corp_b)
        self.assertEqual(top.bonus_manual, 100)
        # Bravo is first now and gets the best moon of its list (moon1, R32)
        self.assertEqual(r.allocations.get(moon=self.moon1).corporation, self.corp_b)

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



class LargePoolTest(IntegrationBase):
    """1000+ moons: forms must stay below Django's DATA_UPLOAD_MAX_NUMBER_FIELDS, R64 never in a round."""

    @classmethod
    def setUpTestData(cls):
        """1500 extra R8 moons."""
        super().setUpTestData()
        Moon.objects.bulk_create([Moon(name=f"BIG I - Moon {i}", system_name="BIG", rarity="R8") for i in range(1500)])

    def test_round_with_1500_moons(self):
        """Creating a round with all moons and applying for 1200 of them works."""
        self.client.force_login(self.officer)
        ids = list(Moon.objects.exclude(rarity="R64").values_list("pk", flat=True))
        resp = self.client.post(reverse("moondistribution:round_create"), {
            "name": "Big", "description": "", "evaluation_start": "2026-05-01", "evaluation_end": "2026-10-31",
            "moon_ids": ",".join(map(str, ids)),
        })
        self.assertEqual(resp.status_code, 302)
        r = Round.objects.get(name="Big")
        self.assertEqual(r.moons.count(), len(ids))
        self.assertFalse(r.moons.filter(rarity="R64").exists())

    def test_r64_is_rejected_in_round(self):
        """Even if an R64 id is posted, the round is not saved with it."""
        self.client.force_login(self.officer)
        resp = self.client.post(reverse("moondistribution:round_create"), {
            "name": "Sneaky", "description": "", "evaluation_start": "2026-05-01", "evaluation_end": "2026-10-31",
            "moon_ids": f"{self.moon_r64.pk},{self.moon1.pk}",
        })
        self.assertEqual(resp.status_code, 200)  # form error, nothing saved
        self.assertFalse(Round.objects.filter(name="Sneaky").exists())
        # and the R64 moon is not even offered
        self.assertNotContains(self.client.get(reverse("moondistribution:round_create")), self.moon_r64.name)

    def test_sortable_tables(self):
        """Round page, apply page and moon list are sortable; rarity sorts by class, then best share."""
        self.moon1.composition = [{"ore": "Zircon", "percent": 59.9}, {"ore": "Bitumens", "percent": 40.1}]
        self.moon1.save()
        now = timezone.now()
        r = Round.objects.create(
            name="S1", application_start=now - timedelta(days=1), application_end=now + timedelta(days=6),
            evaluation_start=date.today() - timedelta(days=182), evaluation_end=date.today(), status=Round.Status.OPEN,
        )
        r.moons.set([self.moon1, self.moon2])
        self.client.force_login(self.officer)
        for url in (reverse("moondistribution:round_detail", args=[r.pk]),
                    reverse("moondistribution:apply", args=[r.pk, self.corp_a.corporation_id]),
                    reverse("moondistribution:moons")):
            resp = self.client.get(url)
            self.assertContains(resp, "md-sortable")
            self.assertContains(resp, 'data-value="32059.9"')  # R32 + 59.9 % best share
            self.assertContains(resp, "59.9%")



class HardeningTest(IntegrationBase):
    """Fixes from the app check: officer access, menu, read-only admin, system check, owner sheet, broker down."""

    def test_officer_without_basic_access(self):
        """mining_officer alone is enough for all pages and the menu entry."""
        from moondistribution.auth_hooks import MoonDistributionMenuItem

        user, _c = _make_user("only_officer", 5099, self.corp_a, perms=("mining_officer",))
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("moondistribution:index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("moondistribution:settings")).status_code, 200)
        request = mock.Mock(user=user, path="/moondistribution/")
        with mock.patch("allianceauth.menu.hooks.MenuItemHook.render", return_value="menu"):
            self.assertEqual(MoonDistributionMenuItem().render(request), "menu")

    def test_results_read_only_in_admin(self):
        """Scores and allocations can't be added, changed or deleted in the Django admin."""
        from django.contrib import admin

        from moondistribution.models import Allocation, CorporationScore

        request = mock.Mock(user=User.objects.create_superuser("root", "r@example.com", "x"))
        for model in (CorporationScore, Allocation):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_system_check_fleet_tracker(self):
        """W002 appears only when no fleet tracker is installed."""
        from moondistribution.checks import data_sources_check

        self.assertEqual([w.id for w in data_sources_check(None)], [])
        with mock.patch("moondistribution.checks.apps.is_installed", side_effect=lambda name: name == "corptools"):
            self.assertEqual([w.id for w in data_sources_check(None)], ["moondistribution.W002"])

    def test_owner_sheet(self):
        """System | Planet | Moon | Type | Corp → owner linked to the AA corp, unknown corps kept as text."""
        self.client.force_login(self.officer)
        paste = (
            "System\tPlanet\tMoon\tType\tCorp\n"
            "I9-ZQZ\t9\t14\tR32\tAlpha Corp\n"
            "R97-CI\t6\t8\tR16\tAbyssus Abyssum Invocat Noricum\n"
        )
        self.client.post(reverse("moondistribution:moon_rarity_import"),
                         {"paste": paste, "source": "paste", "create": "on"})
        a = Moon.objects.get(name="I9-ZQZ IX - Moon 14")
        b = Moon.objects.get(name="R97-CI VI - Moon 8")
        self.assertEqual((a.owner_corporation, a.owner_display), (self.corp_a, "Alpha Corp"))
        self.assertEqual((b.owner_corporation, b.owner_display), (None, "Abyssus Abyssum Invocat Noricum"))

    def test_broker_down_shows_message(self):
        """If Celery is unreachable the officer gets a message, not an error page."""
        from moondistribution.tasks import distribute_round

        r = self._round()
        self.client.force_login(self.officer)
        with mock.patch.object(distribute_round, "delay", side_effect=ConnectionError("broker down")):
            resp = self.client.post(reverse("moondistribution:round_close_now", args=[r.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.CLOSED)

    def test_german_translation(self):
        """German users see the German UI."""
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("moondistribution:moons"), HTTP_ACCEPT_LANGUAGE="de")
        self.assertContains(resp, "Monde")

    def test_officer_apply_shortcut(self):
        """Officer picks a corp → apply page; nothing picked or no alliance → message, no 404."""
        r = self._round()
        self.client.force_login(self.officer)
        url = reverse("moondistribution:officer_apply", args=[r.pk])
        resp = self.client.get(url, {"corporation_id": self.corp_b.corporation_id})
        self.assertRedirects(resp, reverse("moondistribution:apply", args=[r.pk, self.corp_b.corporation_id]),
                             fetch_redirect_response=False)
        self.assertEqual(self.client.get(url).status_code, 302)
        settings = DistributionSettings.get_solo()
        settings.alliance_id = None
        settings.save()
        resp = self.client.get(url, follow=True)
        self.assertContains(resp, "No alliance corps found")
        self.assertContains(self.client.get(reverse("moondistribution:round_detail", args=[r.pk])), "No alliance corps found")


class GuideTest(IntegrationBase):
    """'How it works' page in every Alliance Auth language with the current settings."""

    def test_all_languages_render(self):
        """Every language version renders and shows the configured numbers."""
        from moondistribution.views import GUIDE_LANGUAGES

        settings = DistributionSettings.get_solo()
        settings.application_days, settings.max_wishes, settings.weight_fleet = 9, 17, 33
        settings.max_r16_per_corp = 2
        settings.save()
        self.client.force_login(self.ceo_a)
        for code, _label in GUIDE_LANGUAGES:
            resp = self.client.get(reverse("moondistribution:guide"), {"lang": code})
            self.assertEqual(resp.status_code, 200, code)
            for value in ("9", "17", "33"):
                self.assertContains(resp, value, msg_prefix=code)
            self.assertContains(resp, "md-r16", msg_prefix=code)

    def test_language_from_user(self):
        """Without ?lang the AA language of the user is used, unknown languages fall back to English."""
        self.client.force_login(self.ceo_a)
        self.assertContains(self.client.get(reverse("moondistribution:guide"), HTTP_ACCEPT_LANGUAGE="de"),
                            "So funktioniert die Moon Distribution")
        self.assertContains(self.client.get(reverse("moondistribution:guide"), {"lang": "xx"}),
                            "How the moon distribution works")


class ProbationTest(IntegrationBase):
    """Corps that joined the alliance less than the probation months ago can't take part."""

    def _recent(self, corp, days=20):
        """Mocked ESI says: corp joined the alliance `days` ago."""
        self.join_dates[corp.corporation_id] = timezone.now() - timedelta(days=days)

    def test_new_corp_cannot_apply(self):
        """A corp in its probation is sent back with the end date of its probation."""
        self._recent(self.corp_b)
        from moondistribution.probation import update_join_dates

        update_join_dates([self.corp_b])
        r = self._round()
        self.client.force_login(self.ceo_b)
        resp = self.client.get(reverse("moondistribution:apply", args=[r.pk, 1002]), follow=True)
        self.assertContains(resp, "corps can apply after 3 months")
        resp = self.client.post(reverse("moondistribution:apply", args=[r.pk, 1002]), {"moon_ids": str(self.moon1.pk)})
        self.assertFalse(Application.objects.filter(round=r, corporation=self.corp_b).exists())

    def test_exception_allows_application(self):
        """An officer exception lets the corp apply despite its probation."""
        self._recent(self.corp_b)
        from moondistribution.probation import update_join_dates

        update_join_dates([self.corp_b])
        self.client.force_login(self.officer)
        self.client.post(reverse("moondistribution:corp_exempt", args=[1002]), {"exempt": "1", "reason": "returning corp"})
        record = CorporationProbation.objects.get(corporation=self.corp_b)
        self.assertTrue(record.exempt)
        self.assertEqual(record.exempt_by, self.officer)
        r = self._round()
        self.client.force_login(self.ceo_b)
        self.client.post(reverse("moondistribution:apply", args=[r.pk, 1002]), {"moon_ids": str(self.moon1.pk)})
        self.assertTrue(Application.objects.filter(round=r, corporation=self.corp_b).exists())

    def test_distribution_skips_probation_corps(self):
        """An application from before the corp's (re)join is dropped at distribution time."""
        r = self._round(ended=True)
        for corp, user in ((self.corp_a, self.ceo_a), (self.corp_b, self.ceo_b)):
            app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
            ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
        self._recent(self.corp_a)  # ESI: Alpha just (re)joined – checked again right before the distribution
        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round):
            process_rounds()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE, r.last_error)
        self.assertEqual(r.allocations.get().corporation, self.corp_b)
        self.assertEqual(list(r.scores.values_list("corporation_id", flat=True)), [self.corp_b.pk])
        self.assertEqual(r.settings_snapshot["probation_excluded"], ["Alpha Corp"])

    def test_esi_down_does_not_block(self):
        """No join date (ESI error) never blocks a corp."""
        self.esi_mock.side_effect = ConnectionError("ESI down")
        from moondistribution.probation import blocked_corporation_ids, update_join_dates

        stats = update_join_dates([self.corp_a, self.corp_b])
        self.assertEqual(stats, {"updated": 0, "failed": 2})
        self.assertEqual(blocked_corporation_ids([self.corp_a, self.corp_b]), set())

    def test_probation_off(self):
        """0 months = no probation, even for a corp that joined yesterday."""
        settings = DistributionSettings.get_solo()
        settings.probation_months = 0
        settings.save()
        CorporationProbation.objects.create(corporation=self.corp_b, joined_at=timezone.now() - timedelta(days=1))
        from moondistribution.probation import blocked_corporation_ids

        self.assertEqual(blocked_corporation_ids([self.corp_b]), set())

    def test_corps_page(self):
        """Officer overview shows join date and probation state; members are not allowed."""
        CorporationProbation.objects.create(corporation=self.corp_b, joined_at=timezone.now() - timedelta(days=10))
        self.client.force_login(self.officer)
        resp = self.client.get(reverse("moondistribution:corps"))
        self.assertContains(resp, "In probation")
        self.assertContains(resp, "Bravo Corp")
        self.client.force_login(self.member_b)
        self.assertEqual(self.client.get(reverse("moondistribution:corps")).status_code, 403)


class ExcelTemplateTest(IntegrationBase):
    """Corps that cannot log in (Chinese firewall): officer exports the template, the corp fills it, officer imports."""

    def setUp(self):
        """A third alliance corp without any player in the Auth."""
        super().setUp()
        self.corp_c = EveCorporationInfo.objects.create(
            corporation_id=1003, corporation_name="Charlie Corp", corporation_ticker="CHRLY",
            member_count=40, alliance=EveAllianceInfo.objects.get(alliance_id=ALLIANCE_ID), ceo_id=5099,
        )

    def _export(self, r):
        """Officer downloads the template of round r and gets an openpyxl workbook back."""
        from io import BytesIO

        from openpyxl import load_workbook

        self.client.force_login(self.officer)
        resp = self.client.get(reverse("moondistribution:round_export", args=[r.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])
        return load_workbook(BytesIO(resp.content))

    def _filled(self, wb, ticker, moons, name="charlie.xlsx"):
        """The CEO enters the ticker and an x next to the given moons; returns the file to upload."""
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile

        ws = wb.worksheets[0]
        ws["B3"] = ticker
        wanted = {m.pk for m in moons}
        for row in range(7, ws.max_row + 1):
            if ws.cell(row=row, column=9).value in wanted:
                ws.cell(row=row, column=1).value = "x"
        out = BytesIO()
        wb.save(out)
        return SimpleUploadedFile(name, out.getvalue())

    def test_export_contains_pool_with_details(self):
        """Template lists the pool moons (no R64) with rarity and ID, bilingual header."""
        wb = self._export(self._round())
        ws = wb.worksheets[0]
        names = [ws.cell(row=r, column=3).value for r in range(7, ws.max_row + 1)]
        self.assertIn(self.moon1.name, names)
        self.assertNotIn(self.moon_r64.name, names)
        self.assertIn("想要", ws["A6"].value)
        self.assertIn("meta", wb.sheetnames)

    def test_import_creates_application(self):
        """Imported file becomes the corp's application, marked as entered by an officer."""
        r = self._round()
        upload = self._filled(self._export(r), "[chrly]", [self.moon1, self.moon2])
        resp = self.client.post(reverse("moondistribution:round_import", args=[r.pk]), {"files": [upload]}, follow=True)
        self.assertContains(resp, "Charlie Corp with 2 moons saved")
        app = Application.objects.get(round=r, corporation=self.corp_c)
        self.assertTrue(app.entered_by_officer)
        self.assertEqual(app.submitted_by, self.officer)
        self.assertEqual(app.wishes.count(), 2)

    def test_import_errors(self):
        """Unknown ticker, nothing marked, too many moons, wrong round and non-Excel files are reported, not saved."""
        r = self._round()
        settings = DistributionSettings.get_solo()
        settings.max_wishes = 1
        settings.save()
        from django.core.files.uploadedfile import SimpleUploadedFile

        other = Round.objects.create(name="other", status=Round.Status.DRAFT,
                                     evaluation_start=date.today(), evaluation_end=date.today())
        files = [
            self._filled(self._export(r), "NOPE", [self.moon1], "a.xlsx"),
            self._filled(self._export(r), "CHRLY", [], "b.xlsx"),
            self._filled(self._export(r), "CHRLY", [self.moon1, self.moon2], "c.xlsx"),
            self._filled(self._export(other), "CHRLY", [], "d.xlsx"),
            SimpleUploadedFile("e.xlsx", b"no excel"),
        ]
        resp = self.client.post(reverse("moondistribution:round_import", args=[r.pk]), {"files": files}, follow=True)
        for text in ("is not a corp of the alliance", "no moon marked", "at most 1 allowed",
                     "template of another round", "not an Excel file"):
            self.assertContains(resp, text)
        self.assertFalse(Application.objects.filter(round=r).exists())

    def test_import_respects_probation(self):
        """A corp in its probation can't be imported either."""
        CorporationProbation.objects.create(corporation=self.corp_c, joined_at=timezone.now() - timedelta(days=10))
        r = self._round()
        upload = self._filled(self._export(r), "CHRLY", [self.moon1])
        resp = self.client.post(reverse("moondistribution:round_import", args=[r.pk]), {"files": [upload]}, follow=True)
        self.assertContains(resp, "still in its probation")
        self.assertFalse(Application.objects.filter(round=r).exists())

    def test_members_cannot_export_or_import(self):
        """Only officers."""
        r = self._round()
        self.client.force_login(self.ceo_b)
        self.assertEqual(self.client.get(reverse("moondistribution:round_export", args=[r.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("moondistribution:round_import", args=[r.pk])).status_code, 403)

    def test_no_auth_corp_rated_without_member_criteria(self):
        """Imported corp without players in the Auth: no_auth_data, rated by PvP and fleets only."""
        r = self._round(ended=True)
        app = Application.objects.create(round=r, corporation=self.corp_c, submitted_by=self.officer,
                                         entered_by_officer=True)
        ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
        # officer enters for Bravo (has players in the Auth) → normal rating
        app_b = Application.objects.create(round=r, corporation=self.corp_b, submitted_by=self.officer,
                                           entered_by_officer=True)
        ApplicationWish.objects.create(application=app_b, moon=self.moon2, priority=1)
        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round):
            process_rounds()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE, r.last_error)
        self.assertTrue(r.scores.get(corporation=self.corp_c).no_auth_data)
        self.assertFalse(r.scores.get(corporation=self.corp_b).no_auth_data)

    def test_officer_apply_for_marks_entry(self):
        """'Apply for corp' by an officer marks the application; the corp's own CEO saving clears it."""
        r = self._round()
        self.client.force_login(self.officer)
        self.client.post(reverse("moondistribution:apply", args=[r.pk, 1002]), {"moon_ids": str(self.moon1.pk)})
        self.assertTrue(Application.objects.get(round=r, corporation=self.corp_b).entered_by_officer)
        self.client.force_login(self.ceo_b)
        self.client.post(reverse("moondistribution:apply", args=[r.pk, 1002]), {"moon_ids": str(self.moon1.pk)})
        self.assertFalse(Application.objects.get(round=r, corporation=self.corp_b).entered_by_officer)

    def test_application_without_user_renders(self):
        """An application whose user was deleted (submitted_by empty) must not break the round page."""
        r = self._round()
        Application.objects.create(round=r, corporation=self.corp_c, submitted_by=None)
        self.client.force_login(self.officer)
        with self.settings(DEBUG=True):
            resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        self.assertContains(resp, "Charlie Corp")

    def test_all_pages_need_login(self):
        """No public views."""
        r = self._round()
        for name, args in (("index", []), ("guide", []), ("round_detail", [r.pk]), ("corps", []),
                           ("round_export", [r.pk])):
            resp = self.client.get(reverse(f"moondistribution:{name}", args=args))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn("login", resp.url, name)

    def test_old_template_with_id_in_column_h(self):
        """Templates exported before the rental column existed (ID in column H) can still be imported."""
        r = self._round()
        wb = self._export(r)
        wb.worksheets[0].delete_cols(8)  # remove the rental column → ID is in column H again
        ws = wb.worksheets[0]
        ws["B3"] = "CHRLY"
        for row in range(7, ws.max_row + 1):
            if ws.cell(row=row, column=8).value == self.moon1.pk:
                ws.cell(row=row, column=1).value = "x"
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile

        out = BytesIO()
        wb.save(out)
        self.client.post(reverse("moondistribution:round_import", args=[r.pk]),
                         {"files": [SimpleUploadedFile("old.xlsx", out.getvalue())]})
        self.assertEqual(list(Application.objects.get(round=r, corporation=self.corp_c).wishes.values_list("moon_id", flat=True)),
                         [self.moon1.pk])


class SigTest(IntegrationBase):
    """SIGs (AA groups) reserve moons per round; leaders claim, officers approve, reserved moons are not distributed."""

    def setUp(self):
        """SIG G-4 led by member_b, a second SIG without leader."""
        super().setUp()
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="G-4")
        group.authgroup.group_leaders.add(self.member_b.pk)  # AA uses its own User proxy here
        self.sig = Sig.objects.create(group=group, name="SIG G-4")
        self.other_sig = Sig.objects.create(group=Group.objects.create(name="Other SIG"), name="Other SIG")
        patcher = mock.patch("moondistribution.sigs.notify")
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)

    def _claim(self, user, r, moons, sig=None, reason="Indy"):
        """POST the claim page as user."""
        self.client.force_login(user)
        return self.client.post(reverse("moondistribution:sig_claim", args=[r.pk, (sig or self.sig).pk]),
                                {"moon_ids": ",".join(str(m.pk) for m in moons), "reason": reason})

    def test_leader_claims_and_officer_is_notified(self):
        """SIG leader ticks a moon → claim waits for approval, officers get a notification."""
        r = self._round()
        self._claim(self.member_b, r, [self.moon1])
        claim = SigClaim.objects.get()
        self.assertEqual((claim.moon, claim.status, claim.requested_by), (self.moon1, "pending", self.member_b))
        self.assertTrue(any(call.args[0] == self.officer for call in self.notify.call_args_list))
        # SIG tab visible for the leader
        self.assertContains(self.client.get(reverse("moondistribution:index")), reverse("moondistribution:sigs"))

    def test_non_leader_cannot_claim(self):
        """A CEO who is no SIG leader is sent back, nothing is saved."""
        r = self._round()
        self._claim(self.ceo_a, r, [self.moon1])
        self.assertFalse(SigClaim.objects.exists())

    def test_moon_of_other_sig_cannot_be_claimed(self):
        """A moon already claimed by another SIG is skipped."""
        r = self._round()
        SigClaim.objects.create(round=r, sig=self.other_sig, moon=self.moon1)
        self._claim(self.member_b, r, [self.moon1, self.moon2])
        self.assertEqual(list(SigClaim.objects.filter(sig=self.sig).values_list("moon_id", flat=True)), [self.moon2.pk])

    def test_approved_moon_is_not_offered_and_not_distributed(self):
        """After approval the moon disappears from the application page and from the distribution."""
        r = self._round()
        self._claim(self.member_b, r, [self.moon1])
        claim = SigClaim.objects.get()
        self.client.force_login(self.officer)
        self.client.post(reverse("moondistribution:sig_claim_decide", args=[claim.pk]), {"decision": "approve"})
        claim.refresh_from_db()
        self.assertEqual(claim.status, "approved")
        # application page of a CEO no longer offers moon1
        self.client.force_login(self.ceo_a)
        resp = self.client.get(reverse("moondistribution:apply", args=[r.pk, 1001]))
        self.assertNotContains(resp, self.moon1.name)
        # both corps wanted moon1 – it is reserved, so only moon2 is distributed
        for corp, user in ((self.corp_a, self.ceo_a), (self.corp_b, self.ceo_b)):
            app = Application.objects.create(round=r, corporation=corp, submitted_by=user)
            ApplicationWish.objects.create(application=app, moon=self.moon1, priority=1)
            ApplicationWish.objects.create(application=app, moon=self.moon2, priority=1)
        Round.objects.filter(pk=r.pk).update(application_end=timezone.now() - timedelta(minutes=1))
        with mock.patch.object(distribute_round, "delay", side_effect=distribute_round):
            process_rounds()
        r.refresh_from_db()
        self.assertEqual(r.status, Round.Status.DONE, r.last_error)
        self.assertEqual(list(r.allocations.values_list("moon_id", flat=True)), [self.moon2.pk])
        self.assertEqual(r.settings_snapshot["sig_reserved"], 1)
        resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        self.assertContains(resp, "Reserved for SIGs")
        self.assertContains(resp, "SIG G-4")

    def test_untick_withdraws_and_reject_then_reclaim(self):
        """Unticking removes the claim; a rejected claim goes back to waiting when ticked again."""
        r = self._round()
        self._claim(self.member_b, r, [self.moon1, self.moon2])
        self._claim(self.member_b, r, [self.moon2])
        self.assertEqual(list(SigClaim.objects.values_list("moon_id", flat=True)), [self.moon2.pk])
        claim = SigClaim.objects.get()
        self.client.force_login(self.officer)
        self.client.post(reverse("moondistribution:sig_claim_decide", args=[claim.pk]), {"decision": "reject", "note": "no"})
        claim.refresh_from_db()
        self.assertEqual((claim.status, claim.decision_note), ("rejected", "no"))
        self._claim(self.member_b, r, [self.moon2])
        claim.refresh_from_db()
        self.assertEqual(claim.status, "pending")

    def test_officer_manages_sigs_and_pages_render(self):
        """Officer adds an AA group as SIG, approves all, toggles; SIG page and claim page render."""
        from django.contrib.auth.models import Group

        r = self._round()
        self.client.force_login(self.officer)
        new_group = Group.objects.create(name="Mining SIG")
        self.client.post(reverse("moondistribution:sig_save"), {"group_id": new_group.pk, "name": "SIG Mining"})
        self.assertTrue(Sig.objects.filter(name="SIG Mining").exists())
        SigClaim.objects.create(round=r, sig=self.sig, moon=self.moon1)
        self.client.post(reverse("moondistribution:sig_claims_approve_all", args=[r.pk, self.sig.pk]))
        self.assertEqual(SigClaim.objects.get().status, "approved")
        self.assertEqual(self.client.get(reverse("moondistribution:sigs")).status_code, 200)
        self.assertEqual(self.client.get(reverse("moondistribution:sig_claim", args=[r.pk, self.sig.pk])).status_code, 200)
        self.client.post(reverse("moondistribution:sig_toggle", args=[self.sig.pk]))
        self.sig.refresh_from_db()
        self.assertFalse(self.sig.is_active)
        # members without SIG are sent away from the SIG page, and can't decide claims
        self.client.force_login(self.ceo_a)
        self.assertEqual(self.client.get(reverse("moondistribution:sigs")).status_code, 302)
        self.assertEqual(self.client.post(reverse("moondistribution:sig_claim_decide",
                                                  args=[SigClaim.objects.get().pk]), {"decision": "reject"}).status_code, 403)


class RentalTest(IntegrationBase):
    """Monthly rental from the owner sheet ('Tax Rate 20 %')."""

    SHEET = (
        "System\tPlanet\tMond\tQualität\tCorp\tTax Rate 20 %\n"
        "R-ARKN\t1\t1\tR32\tSIG G-4\t200.000.000,00\n"
        "G-JC9R\t4\t17\tR32\tAbyssus Abyssum Invocat Noricum\t1.095.000.000,00\n"
    )

    def test_rental_imported_and_updated(self):
        """Rental is stored, an existing moon gets the new value even without 'overwrite', shown as 200M / 1.1B."""
        from moondistribution.rarity import apply_moon_data, parse_paste

        apply_moon_data(parse_paste(self.SHEET), overwrite=False, create_missing=True)
        self.moon1.refresh_from_db()
        self.assertEqual(self.moon1.rental_isk, 200_000_000)
        self.assertEqual(self.moon1.rental_display, "200M")
        new = Moon.objects.get(name="G-JC9R IV - Moon 17")
        self.assertEqual(new.rental_display, "1.09B")
        apply_moon_data(parse_paste(self.SHEET.replace("200.000.000,00", "220.000.000,00")), overwrite=False)
        self.moon1.refresh_from_db()
        self.assertEqual(self.moon1.rental_isk, 220_000_000)

    def test_rental_shown_on_round_page(self):
        """The round page shows the rental column when a moon has one."""
        Moon.objects.filter(pk=self.moon1.pk).update(rental_isk=180_000_000)
        r = self._round()
        self.client.force_login(self.ceo_a)
        resp = self.client.get(reverse("moondistribution:round_detail", args=[r.pk]))
        self.assertContains(resp, "Rental / month")
        self.assertContains(resp, "180M")

