# Changelog

## [0.1.12] - 2026-10-29

### Added

- **Excel template for corps without Auth access** (e.g. players behind the Chinese firewall, where the EVE SSO fails): officers download a template of the round with all moons of the pool and their details (region, rarity, best %, composition, current owner), bilingual English/Chinese. The CEO enters the corp ticker and an x next to the wanted moons and sends the file back; the officer imports one or several returned files on the round page. Same rules as a normal application (alliance corp, pool moons only, no R64, max. wishes, probation); every file is reported as imported or with the reason why not. No public page – everything stays behind the login.
- Corps **without any player in the Auth** whose application was entered by an officer (Excel template or "apply for corp") are rated by **PvP and fleets only** – active members and activity rate are left out instead of counting as 0, the weights are re-scaled. Marked on the round page and in the ranking.
- Fleets: with aFAT, fleet members who are not registered in the Auth now count for the corp they are in
- *Corps* page: number of players registered in the Auth per corp and a hint for corps without Auth access
- Guide: Excel template explained in all 12 languages
- Migration `0009_excel_template`

### Changed

- New dependency `openpyxl` (Excel files)

## [0.1.11] - 2026-10-29

### Added

- **Probation for new corps:** corps can only apply after they have been in the alliance for a number of months set in the settings (default 3, 0 = off), counted from their last join. The join date comes from the public EVE alliance history (ESI, no token) and is refreshed when a round is opened, on an officer button and right before a round is distributed; requests never call ESI.
- Applications of corps still in their probation are blocked (with the end date of the probation) and dropped at distribution time; the applicant gets a notification, the round page lists the corps that were not considered
- New officer page **Corps**: alliance corps with EVE member count, join date, end of probation and status; officers can make an **exception** per corp with a reason
- If ESI is not reachable a corp is never blocked (status "unknown")
- Guide: probation explained in all 12 languages (only shown when it is switched on)
- Migration `0008_probation`

### Changed

- Requires `allianceauth>=5.2` and `django-esi>=9.4` (OpenAPI ESI client, part of every AA ≥ 5.2 install)

## [0.1.10] - 2026-10-29

### Added

- **Activity rate** as a new scoring criterion: share of all characters in the corp (EVE member count) that logged in within the active days (Corptools login data) – corps where almost everybody is really active score well regardless of their size; characters not registered in the Auth count as inactive. Own weight in the settings (default 15), not divided in per-member mode.
- Member numbers per applying corp on the round page, live during the application week: members in EVE, players in the Auth, active players, activity rate
- Ranking shows the activity rate (active characters / EVE members) next to active / registered players
- "How it works" guide explains the activity rate in all 12 languages

### Changed

- New default weights: PvP 40, Fleets 35, active members 10, activity rate 15 – migration `0007_activity_rate` switches a settings row that still has the old defaults (50/40/10); custom weights stay and get the activity rate weight 15 (set it to 0 to ignore it)

## [0.1.9] - 2026-10-29

### Added

- **"How it works" guide** for the corps in all 12 Alliance Auth languages (EN, DE, ES, FR, IT, NL, PL, RU, UK, JA, KO, ZH) – explains timeline, application, scoring, bonuses and allocation and always shows the current settings; language follows the user's AA language, switch on the page (e.g. to copy a version to Discord)
- Officer shortcut "apply for corp" also on the round page

### Changed

- **No more priorities:** corps simply tick the moons they want (live counter, limit from the settings). All ticked moons count the same; on its turn a corp gets the best of its moons that is still free (rarity first, then share of the valuable ore). Migration `0006_wishes_without_ranking` removes the unique-priority constraint.
- Applications on the round page show the wanted moons with their rarity; the "Wish #" column is gone

### Fixed

- "Apply for corp" with an empty corp list (no alliance ID set) ended in a 404 – now a hint with a link to the settings

## [0.1.8] - 2026-10-29

### Added

- **Current owner from the owner sheet** (`System | Planet | Moon | Type | Corp`): the corp is linked to the AA corp, unknown corps are kept as text (`Moon.owner_name`, migration `0005_moon_owner_name`); owner editable per moon
- **German translation** of the whole UI
- System check `moondistribution.W002` when no fleet tracker is installed (and `W001` without Corptools)
- GitHub Actions workflow running the tests against Alliance Auth 5.2 and 5.4

### Changed

- Compact moon tables: composition as small chips in its own column (not affected by theme badge styles), empty owner column hidden, best moons (rarity + best share) on top by default
- Moon import from sheets/scans and the Corptools import run as background tasks – the officer gets an AA notification with the result
- Mining Officers no longer need `basic_access` in addition (menu entry and pages)
- Menu badge (open rounds) is cached instead of one query per page load
- Dates shown in EVE format `YYYY-MM-DD HH:MM`
- Distribution results (scores, allocations) are read-only in the Django admin
- Settings use `django-solo`, logging uses AA's extension logger
- Director role only counts from active Corptools characters
- `allianceauth>=5.0,<6`, `allianceauth-corptools>=3.4`; tests are no longer shipped in the package
- README: Docker installation, upgrade, uninstall, data protection notes

### Fixed

- Error page when the Celery broker is unreachable – now a message, the round stays closed for a later re-run
- Two people saving the same corp's application at the same moment could cause an error

## [0.1.7] - 2026-10-29

### Added

- **Sortable moon tables** on the round page, the application page and the moon list – click a column header to sort, **Shift+click** to add further sort levels (shown as 1, 2, … in the header)
- Rarity column sorts by class first and then by the share of the valuable ore (e.g. all R32 with the best % on top, then R16 …)
- New column **"Best %"**: share of the best ore of the moon's own class (falls back to the rarest ore or the % note of the simple sheet)

## [0.1.6] - 2026-10-29

### Changed

- **Mining removed from the scoring** – corps are now rated by PvP (zKillboard), fleet activity (aFAT / AA FAT) and active members only
- New default weights: PvP 50, Fleets 40, active members 10 (an existing settings row that still has the old defaults is switched automatically, custom weights stay)
- Migration `0004_remove_mining` (removes the mining weight and the mining columns of the scores)

## [0.1.5] - 2026-10-29

### Fixed

- `TooManyFieldsSent` when creating a round with 1000+ moons: the moon selection of the round form, the wishlist on the application page and the bulk selection on the moon list are now sent as one field each, so pools of any size stay below Django's `DATA_UPLOAD_MAX_NUMBER_FIELDS`

### Changed

- R64 moons are not offered in the round form and a posted R64 is rejected (covered by tests)

## [0.1.4] - 2026-10-29

### Added

- **Region tabs**: moons are grouped by region (e.g. Esoteria / Feythabolis) on the application page, the round page, the round form and the moon list
- Region is filled automatically from the EVE map data (eve_sde from Corptools, eveuniverse as fallback) on every import and by the daily task; editable per moon for systems that are not in the map data
- Migration `0003_moon_region`

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
