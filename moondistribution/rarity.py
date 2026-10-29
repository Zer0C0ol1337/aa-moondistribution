"""Moon rarity: detect it from moon scans or take it from aa-moonmining, so nobody has to set 1000 moons by hand."""

import logging
import re

from django.apps import apps

from .models import Moon

logger = logging.getLogger(__name__)

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


def ore_rarity(ore_name: str) -> str:
    """Rarity of a moon ore by name ('' if it is no moon ore). 'Glistening Zircon' → 'R32'."""
    words = ore_name.strip().lower().split()
    return ORE_RARITY.get(words[-1], "") if words else ""


def higher_rarity(a: str, b: str) -> str:
    """The rarer of two rarity classes (a moon counts as its best ore)."""
    return a if RARITY_ORDER.get(a, 0) >= RARITY_ORDER.get(b, 0) else b


def parse_rarity_paste(text: str) -> dict:
    """Read pasted moon data and return {moon name: rarity}.

    Understands two formats, mixed in one paste:
    1. EVE moon scan copy (moon name line, then tab-indented ore lines):
           R-ARKN I - Moon 1
               Bitumens    0.30    45492   30000001   40000001   40000002
    2. Simple list, one moon per line: 'R-ARKN I - Moon 1<TAB or ; or ,>R32'
    """
    result, current = {}, None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        fields = [f.strip() for f in re.split(r"\t|;", raw) if f.strip()]
        if not fields:
            continue
        # Header line of the EVE scan copy
        if fields[0].lower() == "moon" and any("product" in f.lower() for f in fields):
            continue
        # Format 2: "<moon name> <sep> R32"
        if len(fields) >= 2 and _RARITY_TOKEN.match(fields[-1].replace(" ", "")):
            name = fields[0]
            result[name] = "R" + _RARITY_TOKEN.match(fields[-1].replace(" ", "")).group(1)
            current = None
            continue
        if "," in raw and len(fields) == 1:
            parts = [p.strip() for p in raw.rsplit(",", 1)]
            if len(parts) == 2 and _RARITY_TOKEN.match(parts[1].replace(" ", "")):
                result[parts[0]] = "R" + _RARITY_TOKEN.match(parts[1].replace(" ", "")).group(1)
                current = None
                continue
        # Format 1: ore line (indented or first field is a moon ore) belongs to the current moon
        rarity = ore_rarity(fields[0])
        if rarity and current:
            result[current] = higher_rarity(result.get(current, ""), rarity)
            continue
        # Anything else that looks like a moon name starts a new moon block
        if " - moon " in raw.lower():
            current = fields[0]
            result.setdefault(current, "")
    return {name: rarity for name, rarity in result.items() if rarity}


def apply_rarities(mapping: dict, overwrite: bool = False) -> dict:
    """Set the rarity of known moons by (case-insensitive) name.

    overwrite=False only fills moons that have no rarity yet, so manual corrections survive.
    """
    stats = {"updated": 0, "unchanged": 0, "unknown": 0}
    moons = {m.name.lower(): m for m in Moon.objects.all()}
    changed = []
    for name, rarity in mapping.items():
        moon = moons.get(name.strip().lower())
        if moon is None:
            stats["unknown"] += 1
            continue
        if moon.rarity == rarity or (moon.rarity and not overwrite):
            stats["unchanged"] += 1
            continue
        moon.rarity = rarity
        changed.append(moon)
    Moon.objects.bulk_update(changed, ["rarity"], batch_size=500)
    stats["updated"] = len(changed)
    return stats


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
