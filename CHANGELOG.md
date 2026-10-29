# Changelog

## [0.1.1] - 2026-10-29

### Added

- Rarity from moon scans: paste any number of in-game moon scan results (or a simple "moon; R32" list) – the rarity is taken from the best ore, variants like "Glistening Zircon" included
- Rarity from aa-moonmining: if installed, missing rarities are filled automatically on every moon import, or all at once with one button
- Moons page: filter by rarity / "no rarity" with counter, search by moon or system, bulk edit (set rarity, activate/deactivate) for ticked moons

## [0.1.0] - 2026-10-29

### Added

- Rounds with activity period and moon pool; opening a round starts a one-week application phase (configurable)
- Moon import from Corptools refineries (Athanor/Tatara) + manual moons with rarity and notes
- Applications with prioritised wishlist by CEO/directors, officers can apply for any corp
- Scoring by mining (Corptools), PvP (zKillboard), active members and fleets (aFAT / AA FAT), configurable weights, optional per-member mode
- Automatic draft-style allocation exactly once when the application phase ends, max. moons per corp
- Distribution protected against double runs (QueueOnce + atomic status switch), no automatic retry
- Fairness: R64 exclusion, R32/R16 limit per corp, automatic compensation bonus from the previous round, manual bonus/malus per corp with visible reason
- Results page, AA notifications for applicants, re-run distribution
- Celery tasks `sync_moons` (daily) and `process_rounds` (every 10 minutes)
