# aa-moondistribution

Alliance Auth plugin for the periodic **moon distribution** of an alliance (e.g. every 6 months).

Corps apply with a moon wishlist, the plugin checks their activity and assigns the moons **automatically** when the application phase ends.

## Features

- **Rounds** with application phase and activity period (default: the 6 months before applications close)
- **Moon pool** imported automatically from Corptools (all Athanors/Tataras of the alliance corps), plus manual moons; rarity (R4–R64) and notes per moon
- **Applications** by the corp CEO or directors (Corptools role data) – wishlist with priorities, changeable until the deadline
- **Scoring** per corp, every criterion scaled 0–100 against the best applicant, weighted average:
  - **Mining** – mined m³ from the Corptools mining ledger
  - **PvP** – ships destroyed according to zKillboard
  - **Active members** – AA users whose main is in the corp and who logged in recently
  - **Fleets** – fleet participations from aFAT (or the AA built-in FAT)
  - optional: values per active member, so small active corps can compete with big ones
- **Automatic allocation** (draft style): best corp gets its top wish, then the next corp, … then the next pass, until every corp reached the max. moons per corp or no wish can be served
- Results page with ranking, raw values and who got which moon; AA notification to every applicant
- Officer tools: create/open/close rounds, re-run distribution, apply on behalf of a corp, settings page

Activity is always attributed via the **main character** of the AA user, so mining/PvP alts in other corps count for the main's corp.

## Requirements

- Alliance Auth ≥ 4
- [allianceauth-corptools](https://github.com/pvyParts/allianceauth-corp-tools) (mining ledger, structures, roles, logins)
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
    "schedule": crontab(minute=5),
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

1. **Settings** → enter the alliance ID, check weights and limits
2. **Moons** → *Import from Corptools*, set the rarity
3. **New round** → dates + moon pool → *Open for applications*
4. After the application end the hourly task distributes automatically

## Optional settings (`local.py`)

| Setting | Default | |
|---|---|---|
| `MOONDIST_APP_NAME` | `Moon Distribution` | Menu label |
| `MOONDIST_ZKILL_USER_AGENT` | plugin + contact | User-Agent for zKillboard |
| `MOONDIST_ZKILL_TIMEOUT` | `20` | Seconds per zKill request |
| `MOONDIST_REFINERY_TYPE_IDS` | `[35835, 35836]` | Athanor, Tatara |

## Notes

- zKillboard stats are monthly, so the PvP window is counted in full months.
- If Corptools has no login data at all (missing scope), all members count as active.
- If zKillboard is down, PvP counts as 0 for the affected corps and the round shows a warning – use *Re-run distribution* later.

## License

GPL-3.0
