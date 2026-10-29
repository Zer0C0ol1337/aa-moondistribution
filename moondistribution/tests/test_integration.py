"""Integration tests: data collection from AA/Corptools, full distribution run and views."""

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter, EveCorporationInfo

from moondistribution.models import Application, ApplicationWish, DistributionSettings, Moon, Round
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


class DistributionIntegrationTest(TestCase):
    """End-to-end: two corps apply, activity decides who gets the contested moon."""

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

        cls.moon1 = Moon.objects.create(name="R-ARKN I - Moon 1", rarity="R64")
        cls.moon2 = Moon.objects.create(name="R-ARKN II - Moon 1", rarity="R32")

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
            "application_start": now.strftime("%Y-%m-%dT%H:%M"),
            "application_end": (now + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M"),
            "evaluation_start": "2026-05-01", "evaluation_end": "2026-10-31",
            "moons": [self.moon1.pk],
        })
        self.assertEqual(resp.status_code, 302)
        r = Round.objects.get(name="H2")
        self.assertEqual(r.status, Round.Status.DRAFT)
        self.assertEqual(list(r.moons.all()), [self.moon1])
