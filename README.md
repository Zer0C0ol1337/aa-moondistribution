# aa-moondistribution

**Version 0.1.14** – see [CHANGELOG](CHANGELOG.md)

Alliance Auth plugin for the periodic **moon distribution** of an alliance (e.g. every 6 months).

Corps apply with a moon wishlist, the plugin checks their activity and assigns the moons **automatically** – exactly once, when the one-week application phase ends.

UI languages: English, German. The "How it works" guide for the corps is available in all 12 Alliance Auth languages.

## Features

- **Rounds**: when the Mining Officer opens a round, applications run for **one week** (configurable), then the round is evaluated and distributed **exactly once**; activity period defaults to the 6 months before applications close
- **Moon pool**
  - paste rows from your moon sheets (`system | planet | moon` plus category, ores with share and/or owner corp – the usual layouts are detected automatically), in-game moon scans or a simple `moon; R32` list – missing moons are created with rarity, **ore composition** and **current owner**
  - optional import of alliance refineries (Athanor/Tatara) from Corptools and of rarities from [aa-moonmining](https://gitlab.com/ErikKalkoken/aa-moonmining)
  - **region tabs** everywhere moons are listed – the region comes from the EVE map data (Corptools' eve_sde, eveuniverse as fallback)
  - filter, search, bulk edit; pools with thousands of moons are supported
- **Probation**: corps can only apply after N months in the alliance (setting, default 3, 0 = off), counted from their last join according to the EVE alliance history; officers can make an exception per corp (page *Corps*)
- **SIG reservations**: SIGs (AA groups, e.g. G-4) claim moons for a round, a Mining Officer approves them; approved moons are not distributed (tab *SIGs*)
- **Monthly rental** per moon from the owner sheet (`… | Corp | Tax Rate 20 %`), shown next to the moons
- **Applications** by the corp CEO or directors (Corptools role data) – tick the wanted moons (no ranking, all count the same), changeable until the deadline
- **Excel template for corps without Auth access** (e.g. behind the Chinese firewall): officers export the round's moons with all details (English/Chinese), the CEO marks the wanted moons and sends the file back, the officer imports it (several files at once); such corps are rated by PvP and fleets only
- **"How it works" guide** for the corps in all Alliance Auth languages, always showing the current settings
- **Scoring** per corp, every criterion scaled 0–100 against the best applicant, weighted average:
  - **PvP** – ships destroyed according to zKillboard (default weight 40)
  - **Fleets** – fleet participations from aFAT or the AA built-in fleet activity tracking (default weight 35); with aFAT every FAT counts with a **factor per fleet type** (e.g. *Mining* = 0.5), set in the settings; types without a factor use the default value (1)
  - **Active members** – AA users whose main is in the corp and who logged in recently (default weight 10)
  - **Activity rate** – share of all characters in the corp (EVE member count) that logged in recently; unregistered characters count as inactive (default weight 15)
  - **Intel / reports** – points for wormhole reports, intel and similar work that the officers enter per corp and round; the report types and their points are set in the settings (default weight 0 = off)
  - all weights, the value of one FAT per fleet type and the points per report type are adjustable in the settings
  - optional: values per active member, so small active corps can compete with big ones
- **Fairness**
  - R64 moons are never distributed (setting, on by default)
  - limit of R32 (default 1) and optionally R16 moons per corp and round
  - automatic **compensation bonus** for corps that applied last round and got no moon (+15) or no R32 (+8)
  - **manual bonus/malus** per corp and round with a reason that everyone can see
- **Automatic allocation** (draft style): in score order every corp gets the best of its ticked moons that is still free (rarity, then share of the valuable ore), then the next pass starts – until every corp reached the max. moons per corp or none of its moons is free
- **Sortable tables** (Shift+click for multiple levels); rarity sorts by class, then by the share of the valuable ore
- Officers see live how many corps want each moon during the application week, and the member numbers (EVE / Auth / active / activity rate) of every applying corp
- Results page with ranking, raw values, bonuses and who got which moon; AA notification to every applicant

Activity is always attributed via the **main character** of the AA user, so alts in other corps count for the main's corp.

## Requirements

- Alliance Auth 5.2 or newer (5.x)
- *recommended:* [allianceauth-corptools](https://github.com/pvyParts/allianceauth-corp-tools) ≥ 3.4, installed with `pip install "aa-moondistribution[corptools]"` (roles, logins, refineries, EVE map data). Without it the app still runs; the moon import, director roles and login-based activity need it.
- a fleet tracker: [aFAT](https://github.com/ppfeufer/allianceauth-afat) or `allianceauth.fleetactivitytracking` – without one the fleet criterion is 0 for everybody (system check `moondistribution.W002` warns)
- optional: [aa-moonmining](https://gitlab.com/ErikKalkoken/aa-moonmining) for automatic moon rarity

## Installation

### Docker (aa-docker)

1. Add to `conf/requirements.txt`:
   ```
   aa-moondistribution @ git+https://github.com/Zer0C0ol1337/aa-moondistribution.git
   ```
2. Add to `conf/local.py` (see [Settings](#localpy))
3. Build, start and migrate:
   ```bash
   docker compose build --no-cache
   docker compose --env-file=.env up -d --force-recreate
   docker compose exec allianceauth_gunicorn bash
   auth migrate
   exit
   ```

### Bare metal / venv

```bash
pip install git+https://github.com/Zer0C0ol1337/aa-moondistribution.git
# local.py as below, then
python manage.py migrate moondistribution
```
Restart supervisor (gunicorn, worker, beat). The app has no static files, `collectstatic` is not needed.

### local.py

```python
INSTALLED_APPS += [
    "moondistribution",
]

from celery.schedules import crontab

# daily import of the alliance refineries from Corptools (optional if you only use sheets)
CELERYBEAT_SCHEDULE["moondistribution_sync_moons"] = {
    "task": "moondistribution.tasks.sync_moons",
    "schedule": crontab(minute=15, hour=4),
}
# every 10 minutes: close rounds whose application week is over and distribute them once
CELERYBEAT_SCHEDULE["moondistribution_process_rounds"] = {
    "task": "moondistribution.tasks.process_rounds",
    "schedule": crontab(minute="*/10"),
}
```

## Permissions

| Permission | Who | What |
|---|---|---|
| `moondistribution.basic_access` | Member state | Menu entry, rounds and results; CEOs/directors can apply for their corp |
| `moondistribution.mining_officer` | Mining Officers | Everything: rounds, moons, settings, bonuses, apply for any corp (no `basic_access` needed in addition) |

Superusers have all permissions and act as officers.

SIG leaders need no extra permission: the group leaders of an AA group that an officer added as SIG get the *SIGs* tab automatically (they still need `basic_access`, usually via the member state).

## First steps

1. **Settings** → alliance ID, probation, weights, value of one FAT per fleet type (name exactly as in aFAT), report types with points (intel / wormhole reports), limits and fairness rules
   **Corps** → check join dates (*Update join dates from ESI*) and set exceptions if needed
2. **Moons** → *Add moons / rarity from scans*: paste your moon sheets (all rows incl. header – several sheets one after another are fine), keep *Create missing moons* ticked; an owner sheet (`System | Planet | Moon | Type | Corp`) sets the current owners. The import runs in the background, you get a notification with the result.
   **SIGs** → add the AA groups that are SIGs; their **group leaders** (AA Group Management) can then claim moons for each round
3. **New round** → activity period + moon pool (per region) → optional manual bonus points → *Open for applications*
4. When the week is over, `process_rounds` closes the round and distributes it once

## Upgrade

Docker: rebuild (`docker compose build --no-cache`), restart (`up -d --force-recreate`) and run `auth migrate`.
Bare metal: `pip install -U git+https://github.com/Zer0C0ol1337/aa-moondistribution.git`, `python manage.py migrate`, restart supervisor.
Migrations are additive – `migrate` only applies the missing ones.

## Uninstall

1. Remove all data of the app (only this app's tables):
   ```bash
   python manage.py migrate moondistribution zero        # Docker: auth migrate moondistribution zero
   ```
2. Remove `"moondistribution"` from `INSTALLED_APPS` and both `CELERYBEAT_SCHEDULE["moondistribution_…"]` entries from `local.py`, remove the line from `requirements.txt` (Docker) or `pip uninstall aa-moondistribution`.
3. Optional – remove the permissions and content types of this app only:
   ```bash
   python manage.py shell -c "from django.contrib.contenttypes.models import ContentType; ContentType.objects.filter(app_label='moondistribution').delete()"
   ```
   Don't use `remove_stale_contenttypes --include-stale-apps`, it also removes leftovers of other apps.

## Optional settings (`local.py`)

| Setting | Default | |
|---|---|---|
| `MOONDIST_APP_NAME` | `Moon Distribution` | Menu label |
| `MOONDIST_ZKILL_USER_AGENT` | plugin + contact | User-Agent for zKillboard |
| `MOONDIST_ZKILL_TIMEOUT` | `20` | Seconds per zKillboard request |
| `MOONDIST_REFINERY_TYPE_IDS` | `[35835, 35836]` | Athanor, Tatara |

## Notes

### Setup notes (Corptools and its dependencies)

Installing Corptools 3.5.x on Alliance Auth 5.5 or newer needed these pins, found during a dev installation:
- `httpx>=0.27`: Corptools uses it but does not declare it.
- `django-eveonline-sde==0.2.0`: newer releases do not match the fields Corptools expects (`name_en`).
- `django-eveuniverse==2.2.0`: version 2.0.0 and 2.1.0 require `django-esi<10`, which conflicts with Alliance Auth 5.5 and newer. Version 2.2.0 accepts `django-esi` 8 to 10.
- `modeltranslation` must come **before** all other apps in `INSTALLED_APPS` (`INSTALLED_APPS = ["modeltranslation"] + INSTALLED_APPS`), otherwise `eve_sde` fails on `name_en`.
- After installing, run `auth esde_load_sde` and `auth ct_setup` once.

### Trust and permissions

- Superusers pass every permission check (Django's `has_perm` behaviour), so they can see and change everything.
- Mining Officers decide moon assignments and bonuses. The permission `mining_officer` is therefore a trust role; give it only to people you trust with alliance rewards.
- Corporation CEOs and directors can only apply for their own corporation; the app enforces this in code.

### External dependency: zKillboard

The PvP criterion comes from zKillboard. If zKillboard is unreachable for a corporation, that corporation gets PvP 0 and is marked with a zKillboard error flag in the ranking. The distribution message states how many corporations were affected. The timeout is set by `MOONDIST_ZKILL_TIMEOUT` (default 20 seconds).

### Data protection

The app stores character names, corporation names and tickers, applications with the names of the submitting user, round results, and the optional intel/report entries with the name of the officer who entered them. Data about people without an account is limited to corporation data. Nothing is sent to third parties except the requests to zKillboard (kill numbers by corporation) and the public ESI alliance history (join date of corporations). Retention: the last finished round stays in the database until the next distribution is finished. Then all older finished rounds are deleted automatically, together with their applications, allocations and scores. Open and unfinished rounds are not touched; they can be deleted by an officer on the round page.



- **Outgoing traffic:** during a distribution the plugin calls the public zKillboard stats API once per applying corp (only corporation IDs are sent).
- **ESI:** only the public endpoint `GET /corporations/{corporation_id}/alliancehistory/` (no token, no scopes) for the probation – for all alliance corps when a round is opened or an officer clicks *Update join dates from ESI*, and for the applicants right before the distribution. The automatic calls are skipped when the probation is 0. If ESI is down the stored date is kept; a corp without any known date is never blocked.
- zKillboard stats are monthly, so the PvP window is counted in full months. If zKillboard is down, PvP counts as 0 for the affected corps and the round shows a warning – use *Re-run distribution* later.
- **Active members** and the **activity rate** use the Corptools login data (`last_known_login`); if there is none at all, every registered member counts as active and the activity rate is 0 for everybody. The EVE member count comes from Alliance Auth's corp data (updated daily).
- **Directors** are taken from the Corptools role data of active Corptools characters; role changes show up after the next Corptools update.
- The Corptools refinery import only sees corps that added a **corp token** in Corptools – otherwise use the sheet import.
- A failed distribution is not retried automatically; the round shows the error and an officer starts it again with *Re-run distribution*. *Close now & distribute* ends the application phase early.
- **Excel template:** the export contains the round's moon pool and current owners – it is meant for the CEOs of the corps. Imported applications are saved as entered by the importing officer. Uploads are limited to 5 MB per file and only accepted from officers.
- **Fleets of unregistered players:** with aFAT, fleet members without an Auth account count for their current corp; registered players count for the corp of their main.
- **Data stored:** who submitted an application (AA user), the comment, which officer set a bonus. Bonus reasons are visible to all members.
- The pages need JavaScript (as Alliance Auth itself).

## Development

Tests run in an Alliance Auth test project, see `.github/workflows/tests.yml`.
The guide templates (`templates/moondistribution/guide/<lang>.html`) are generated by `tools/generate_guide.py` – edit the texts there and run
`python tools/generate_guide.py moondistribution/templates/moondistribution/guide`.

## License

GPL-3.0
