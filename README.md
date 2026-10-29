# aa-moondistribution

**Version 0.1.3** – see [CHANGELOG](CHANGELOG.md)

Alliance Auth plugin for the periodic **moon distribution** of an alliance (e.g. every 6 months).

Corps apply with a moon wishlist, the plugin checks their activity and assigns the moons **automatically** when the application phase ends.

## Features

- **Rounds**: when the Mining Officer opens a round, applications run for **one week** (configurable), then the round is evaluated and distributed **exactly once**; activity period defaults to the 6 months before applications close
- **Moon pool** imported automatically from Corptools (all Athanors/Tataras of the alliance corps), plus manual moons; rarity (R4–R64) and notes per moon
- **Moons and rarity without manual work**: paste in-game moon scans (any number at once), a "moon; R32" list or rows from your moon sheets (`system | planet | moon` + category and/or ores with share) – missing moons are created with rarity and **ore composition**, existing ones are completed – or take it from [aa-moonmining](https://gitlab.com/ErikKalkoken/aa-moonmining) if installed; bulk edit and "no rarity" filter for the rest
- **Applications** by the corp CEO or directors (Corptools role data) – wishlist with priorities, changeable until the deadline
- **Scoring** per corp, every criterion scaled 0–100 against the best applicant, weighted average:
  - **Mining** – mined m³ from the Corptools mining ledger
  - **PvP** – ships destroyed according to zKillboard
  - **Active members** – AA users whose main is in the corp and who logged in recently
  - **Fleets** – fleet participations from aFAT (or the AA built-in FAT)
  - optional: values per active member, so small active corps can compete with big ones
- **Fairness**:
  - R64 moons can be excluded (kept by the alliance) – on by default
  - limit of R32 (default 1) and optionally R16 moons per corp and round
  - automatic **compensation bonus** for corps that applied last round and got no moon (+15) or no R32 (+8)
  - **manual bonus/malus** per corp and round with a reason that everyone can see
- **Automatic allocation** (draft style): best corp gets its top wish, then the next corp, … then the next pass, until every corp reached the max. moons per corp or no wish can be served
- Officers see live how many corps want each moon during the application week
- Results page with ranking, raw values and who got which moon; AA notification to every applicant
- Officer tools: create/open/close rounds, re-run distribution, apply on behalf of a corp, settings page

Activity is always attributed via the **main character** of the AA user, so mining/PvP alts in other corps count for the main's corp.

## Requirements

- Alliance Auth ≥ 4
- [allianceauth-corptools](https://github.com/pvyParts/allianceauth-corp-tools) (mining ledger, structures, roles, logins)
- optional: [aa-moonmining](https://gitlab.com/ErikKalkoken/aa-moonmining) for automatic moon rarity
- optional: [aFAT](https://github.com/ppfeufer/allianceauth-afat) or the AA built-in fleet activity tracking

## Installation

```bash
pip install git+https://github.com/Zer0C0ol1337/aa-moondistribution.git
```

Add to `INSTALLED_APPS` in `local.py`:

```python
INSTALLED_APPS += [
    "moondistribution",
]
```

Add the periodic tasks to `local.py`:

```python
from celery.schedules import crontab

CELERYBEAT_SCHEDULE["moondistribution_sync_moons"] = {
    "task": "moondistribution.tasks.sync_moons",
    "schedule": crontab(minute=15, hour=4),
}
CELERYBEAT_SCHEDULE["moondistribution_process_rounds"] = {
    "task": "moondistribution.tasks.process_rounds",
    "schedule": crontab(minute="*/10"),
}
```

Then:

```bash
python manage.py migrate moondistribution
python manage.py collectstatic --noinput
```

Restart supervisor (gunicorn, worker, beat).

## Permissions

| Permission | Who | What |
|---|---|---|
| `moondistribution.basic_access` | Member state | See rounds/results, apply as CEO/director |
| `moondistribution.mining_officer` | Mining Officers | Rounds, moons, settings, apply for any corp |

## First steps

1. **Settings** → enter the alliance ID, check weights, limits and fairness rules
2. **Moons** → *Import from Corptools* and/or *Add moons / rarity from scans* (paste scans or a moon list) – with aa-moonmining installed rarities are filled automatically
3. **New round** → activity period + moon pool → optional manual bonus points → *Open for applications* (starts the one-week application phase)
4. When the week is over, `process_rounds` (every 10 minutes) closes the round and distributes it once

## Optional settings (`local.py`)

| Setting | Default | |
|---|---|---|
| `MOONDIST_APP_NAME` | `Moon Distribution` | Menu label |
| `MOONDIST_ZKILL_USER_AGENT` | plugin + contact | User-Agent for zKillboard |
| `MOONDIST_ZKILL_TIMEOUT` | `20` | Seconds per zKill request |
| `MOONDIST_REFINERY_TYPE_IDS` | `[35835, 35836]` | Athanor, Tatara |

## Notes

- zKillboard stats are monthly, so the PvP window is counted in full months.
- The Corptools import only sees refineries of corps that added a **corp token** in Corptools. If most corps did not, add the moons via *Add moons / rarity from scans* instead.
- If Corptools has no login data at all (missing scope), all members count as active.
- If zKillboard is down, PvP counts as 0 for the affected corps and the round shows a warning – use *Re-run distribution* later.
- A failed distribution is not retried automatically; the round shows the error and an officer can start it again with *Re-run distribution*.
- *Close now & distribute* ends the application phase early.

## License

GPL-3.0
