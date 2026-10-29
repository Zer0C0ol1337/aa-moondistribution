# Changelog

## [0.1.0] - 2026-10-29

### Added

- Rounds with application phase, activity period and moon pool
- Moon import from Corptools refineries (Athanor/Tatara) + manual moons with rarity and notes
- Applications with prioritised wishlist by CEO/directors, officers can apply for any corp
- Scoring by mining (Corptools), PvP (zKillboard), active members and fleets (aFAT / AA FAT), configurable weights, optional per-member mode
- Automatic draft-style allocation when applications close, max. moons per corp
- Results page, AA notifications for applicants, re-run distribution
- Celery tasks `sync_moons` (daily) and `process_rounds` (hourly)
