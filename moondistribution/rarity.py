"""Moon data import: name, rarity and ore composition from pasted sheets / moon scans, or from aa-moonmining.

Nobody should have to enter 1000+ moons by hand, so the paste parser is deliberately flexible:
it works row by row and looks for "system | planet | moon" followed by ores and their share,
no matter which columns come before or after.
"""

import re

from django.apps import apps

from allianceauth.services.hooks import get_extension_logger

from .models import Moon

logger = get_extension_logger(__name__)

# Base moon ores per rarity class. Variants ("Brimful", "Glistening", "Copious", "Twinkling", ...)
# are matched by the base name at the end of the ore name.
ORE_RARITY = {
    "bitumens": "R4", "coesite": "R4", "sylvite": "R4", "zeolites": "R4",
    "cobaltite": "R8", "euxenite": "R8", "scheelite": "R8", "titanite": "R8",
    "chromite": "R16", "otavite": "R16", "sperrylite": "R16", "vanadinite": "R16",
    "carnotite": "R32", "cinnabar": "R32", "pollucite": "R32", "zircon": "R32",
    "loparite": "R64", "monazite": "R64", "xenotime": "R64", "ytterbite": "R64",
}
RARITY_ORDER = {"R4": 4, "R8": 8, "R16": 16, "R32": 32, "R64": 64}
_RARITY_TOKEN = re.compile(r"^R ?(4|8|16|32|64)$", re.IGNORECASE)
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_NOT_OWNER = {"ok", "yes", "no", "ja", "nein", "x", "sum", "class", "type", "corp", "owner"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def ore_rarity(ore_name: str) -> str:
    """Rarity of a moon ore by name ('' if it is no moon ore). 'Glistening Zircon' → 'R32'."""
    words = ore_name.strip().lower().split()
    return ORE_RARITY.get(words[-1], "") if words else ""


def higher_rarity(a: str, b: str) -> str:
    """The rarer of two rarity classes (a moon counts as its best ore)."""
    return a if RARITY_ORDER.get(a, 0) >= RARITY_ORDER.get(b, 0) else b


def rarity_token(cell: str) -> str:
    """'R32' / 'r 32' → 'R32', anything else → ''."""
    match = _RARITY_TOKEN.match(cell.replace(" ", ""))
    return "R" + match.group(1) if match else ""


def to_roman(number: int) -> str:
    """Planet number as roman numeral like in EVE moon names (6 → 'VI')."""
    values = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for value, numeral in values:
        while number >= value:
            result += numeral
            number -= value
    return result


def parse_percent(cell: str):
    """'24.5%' / '24,5 %' / '0.245' (scan fraction) → 24.5; None if it is no number."""
    raw = cell.strip().replace(" ", "")
    has_percent = raw.endswith("%")
    raw = raw.rstrip("%").replace(",", ".")
    if not _NUMBER.match(raw):
        return None
    value = float(raw)
    if not has_percent and 0 < value <= 1:
        value *= 100  # EVE scan copy gives fractions (0.30 = 30 %)
    return round(value, 1)


def canonical_ore(name: str) -> str:
    """Normalise spelling: 'coesite' → 'Coesite', 'glistening zircon' → 'Glistening Zircon'."""
    return " ".join(word.capitalize() for word in name.split())


def system_from_moon_name(name: str) -> str:
    """'R-ARKN I - Moon 1' → 'R-ARKN', 'Old Man Star VII - Moon 2' → 'Old Man Star'."""
    head = re.split(r" - moon ", name, flags=re.IGNORECASE)[0].strip()
    return head.rsplit(" ", 1)[0] if " " in head else head


def ores_from_cells(cells: list) -> list:
    """All '<ore> | <share>' pairs in a row → [{'ore': 'Zircon', 'percent': 24.5}, ...]."""
    composition = []
    for i, cell in enumerate(cells):
        if not ore_rarity(cell):
            continue
        percent = parse_percent(cells[i + 1]) if i + 1 < len(cells) else None
        composition.append({"ore": canonical_ore(cell), "percent": percent})
    return composition


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_sheet_row(cells: list):
    """One sheet row → (moon name, entry) or None.

    Looks for the first 'system | planet | moon' triple (planet and moon as numbers) anywhere in the row,
    so leading key columns (ESO: '29YH-V82') or a category column (Fey: 'R64') don't matter.
    entry = {'rarity': 'R32', 'composition': [...], 'note': '28 %'}
    """
    for i in range(len(cells) - 2):
        system, planet, moon = cells[i].strip(), cells[i + 1].strip(), cells[i + 2].strip()
        if not system or _NUMBER.match(system.rstrip("%")) or rarity_token(system):
            continue
        if not (planet.isdigit() and moon.isdigit()) or int(planet) < 1 or int(moon) < 1:
            continue
        name = f"{system} {to_roman(int(planet))} - Moon {int(moon)}"
        rest = cells[i + 3:]
        composition = ores_from_cells(rest)

        # Rarity: explicit category cell (R32) anywhere in the row, otherwise the best ore
        rarity = next((rarity_token(c) for c in cells if rarity_token(c)), "")
        if not rarity:
            for ore in composition:
                rarity = higher_rarity(rarity, ore_rarity(ore["ore"]))

        # Owner sheet: a text cell after the triple that is no ore, category, number or marker → corp name
        owner = ""
        for cell in rest:
            c = cell.strip()
            if (len(c) >= 3 and any(ch.isalpha() for ch in c) and not rarity_token(c) and not ore_rarity(c)
                    and parse_percent(c) is None and c.lower() not in _NOT_OWNER):
                owner = c
                break

        # Simple sheet without ores: the number right after the category is the share of the rare ore
        note = ""
        if not composition:
            for j, cell in enumerate(rest):
                if rarity_token(cell) and j + 1 < len(rest):
                    share = parse_percent(rest[j + 1] + ("%" if "%" not in rest[j + 1] else ""))
                    if share is not None:
                        note = f"{share:g} %"
                    break
        if not rarity:
            return None
        return name, {"rarity": rarity, "composition": composition, "note": note, "owner": owner}
    return None


def parse_paste(text: str) -> dict:
    """Read pasted moon data → {moon name: {'rarity', 'composition', 'note'}}.

    Understands, mixed in one paste:
    1. Sheet rows copied from Google Sheets/Excel – any layout with 'system | planet | moon' and
       optionally category, ores and shares (alliance sheet, Fey sheet, ESO sheet)
    2. EVE moon scan copy (moon name line, then tab-indented ore lines with share)
    3. Simple list, one moon per line: 'R-ARKN I - Moon 1; R32' (tab, ; or , as separator)
    """
    result, current = {}, None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        cells = [c.strip() for c in raw.split("\t")]
        fields = [f.strip() for f in re.split(r"\t|;", raw) if f.strip()]

        # EVE scan header
        if fields and fields[0].lower() == "moon" and any("product" in f.lower() for f in fields):
            continue

        # 1) sheet row
        row = parse_sheet_row(cells)
        if row:
            result[row[0]] = row[1]
            current = None
            continue

        # 2) EVE scan: ore line belongs to the current moon
        if fields and ore_rarity(fields[0]) and current:
            entry = result[current]
            percent = parse_percent(fields[1]) if len(fields) > 1 else None
            entry["composition"].append({"ore": canonical_ore(fields[0]), "percent": percent})
            entry["rarity"] = higher_rarity(entry["rarity"], ore_rarity(fields[0]))
            continue

        # 3) simple list "moon name ; R32" / "moon name, R32"
        parts = fields if len(fields) >= 2 else [p.strip() for p in raw.rsplit(",", 1)]
        if len(parts) >= 2 and rarity_token(parts[-1]) and " - moon " in parts[0].lower():
            result[parts[0]] = {"rarity": rarity_token(parts[-1]), "composition": [], "note": ""}
            current = None
            continue

        # 2) EVE scan: a moon name line starts a new block
        if " - moon " in raw.lower():
            current = fields[0]
            result.setdefault(current, {"rarity": "", "composition": [], "note": ""})

    return {name: entry for name, entry in result.items() if entry["rarity"]}


def parse_rarity_paste(text: str) -> dict:
    """{moon name: rarity} – short form of parse_paste()."""
    return {name: entry["rarity"] for name, entry in parse_paste(text).items()}


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------

def region_names_for(systems) -> dict:
    """{system name: region name} from the EVE map data – eve_sde (Corptools) first, then eveuniverse."""
    wanted = {s for s in systems if s}
    result = {}
    if wanted and apps.is_installed("eve_sde"):
        from eve_sde.models import SolarSystem

        result.update({
            name: region for name, region in SolarSystem.objects.filter(name__in=wanted)
            .values_list("name", "constellation__region__name") if region
        })
    missing = wanted - set(result)
    if missing and apps.is_installed("eveuniverse"):
        from eveuniverse.models import EveSolarSystem

        result.update({
            name: region for name, region in EveSolarSystem.objects.filter(name__in=missing)
            .values_list("name", "eve_constellation__eve_region__name") if region
        })
    # case-insensitive access (sheets sometimes differ in case)
    return {**result, **{k.lower(): v for k, v in result.items()}}


def fill_missing_regions() -> int:
    """Set region_name for all moons that don't have one yet. Returns the number of updated moons."""
    moons = list(Moon.objects.filter(region_name=""))
    regions = region_names_for({m.system_name for m in moons})
    changed = []
    for moon in moons:
        region = regions.get(moon.system_name) or regions.get(moon.system_name.lower())
        if region:
            moon.region_name = region
            changed.append(moon)
    Moon.objects.bulk_update(changed, ["region_name"], batch_size=500)
    return len(changed)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def apply_moon_data(entries: dict, overwrite: bool = False, create_missing: bool = False) -> dict:
    """Write rarity, composition and note to the moons (matched by case-insensitive name).

    entries: {moon name: {'rarity': 'R32', 'composition': [...], 'note': ''}} (or {name: 'R32'})
    overwrite=False only fills empty fields, so manual corrections survive.
    create_missing=True adds moons that are not in the list yet – needed when the refineries
    are not visible in Corptools.
    """
    stats = {"created": 0, "updated": 0, "unchanged": 0, "unknown": 0, "owners_not_in_aa": 0}
    moons = {m.name.lower(): m for m in Moon.objects.all()}

    # Owner names from the paste → AA corps (case-insensitive name match)
    from allianceauth.eveonline.models import EveCorporationInfo

    owner_names = {e.get("owner", "").lower() for e in entries.values() if isinstance(e, dict) and e.get("owner")}
    corps = {
        c.corporation_name.lower(): c
        for c in EveCorporationInfo.objects.all().only("id", "corporation_name")
        if c.corporation_name.lower() in owner_names
    }
    stats["owners_not_in_aa"] = len(owner_names - set(corps))
    changed, new = [], {}
    for name, entry in entries.items():
        if isinstance(entry, str):
            entry = {"rarity": entry, "composition": [], "note": ""}
        clean = " ".join(name.split())
        rarity, composition, note = entry["rarity"], entry.get("composition") or [], entry.get("note") or ""
        owner = entry.get("owner") or ""
        owner_corp = corps.get(owner.lower()) if owner else None
        moon = moons.get(clean.lower())

        if moon is None:
            if create_missing and clean.lower() not in new:
                new[clean.lower()] = Moon(
                    name=clean, system_name=system_from_moon_name(clean),
                    rarity=rarity, composition=composition, notes=note,
                    owner_name=owner, owner_corporation=owner_corp,
                )
            elif not create_missing:
                stats["unknown"] += 1
            continue

        dirty = False
        if rarity and moon.rarity != rarity and (not moon.rarity or overwrite):
            moon.rarity, dirty = rarity, True
        if composition and moon.composition != composition and (not moon.composition or overwrite):
            moon.composition, dirty = composition, True
        if note and moon.notes != note and (not moon.notes or overwrite):
            moon.notes, dirty = note, True
        if owner and moon.owner_name != owner and (not moon.owner_name or overwrite):
            moon.owner_name, moon.owner_corporation, dirty = owner, owner_corp, True
        if dirty:
            changed.append(moon)
        else:
            stats["unchanged"] += 1

    Moon.objects.bulk_update(
        changed, ["rarity", "composition", "notes", "owner_name", "owner_corporation"], batch_size=500,
    )
    Moon.objects.bulk_create(new.values(), batch_size=500)
    stats["updated"] = len(changed)
    stats["created"] = len(new)
    fill_missing_regions()
    return stats


def apply_rarities(mapping: dict, overwrite: bool = False, create_missing: bool = False) -> dict:
    """Backwards compatible wrapper: {moon name: rarity} → apply_moon_data()."""
    return apply_moon_data(mapping, overwrite=overwrite, create_missing=create_missing)


def rarities_from_moonmining() -> dict:
    """{moon name: rarity} from aa-moonmining (if installed) – it knows the ore composition from its scans."""
    if not apps.is_installed("moonmining"):
        return {}
    from moonmining.models import Moon as MMMoon

    mapping = {}
    for name, rarity_class in MMMoon.objects.filter(rarity_class__gt=0).values_list("eve_moon__name", "rarity_class"):
        key = f"R{rarity_class}"
        if key in RARITY_ORDER and name:
            mapping[name] = key
    return mapping
