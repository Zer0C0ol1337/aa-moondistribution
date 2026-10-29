# Changelog

## [0.1.3] - 2026-10-29

### Added

- Sheet import: rows copied from Google Sheets/Excel are recognised directly – any layout with `system | planet | moon` plus category and/or ores with their share (alliance sheet, Fey sheet, ESO sheet); the planet number becomes the EVE roman numeral ("02V-BK VI - Moon 15")
- **Moon composition**: ores and their share are stored per moon (from sheets and in-game scans) and shown on the moons page, the round page and when applying; without a category column the rarity is taken from the best ore
- Rarity colours like in the alliance sheets: R64 red, R32 orange, R16 green, R8 blue, R4 white
- Migration `0002_moon_composition`
- Round page (officers): number of applications per moon, live during the application week, most wanted moons first
- Moon note shown next to the owner on the round page

## [0.1.2] - 2026-10-29

### Added

- Moon scans / moon list can now also **create** missing moons (name, system and rarity) – for alliances whose corps have no corp token in Corptools, so the refineries are not visible there

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
