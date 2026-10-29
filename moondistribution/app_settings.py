"""Static settings that can be overridden in local.py (everything else lives in the settings page)."""

from django.conf import settings

# Name shown in the AA side menu
MOONDIST_APP_NAME = getattr(settings, "MOONDIST_APP_NAME", "Moon Distribution")

# User-Agent for zKillboard requests – zKill asks for a contact in the UA
MOONDIST_ZKILL_USER_AGENT = getattr(
    settings,
    "MOONDIST_ZKILL_USER_AGENT",
    "aa-moondistribution (Alliance Auth plugin; contact: LeggaSchnegge [3THEL])",
)

# Timeout in seconds for a single zKillboard request
MOONDIST_ZKILL_TIMEOUT = getattr(settings, "MOONDIST_ZKILL_TIMEOUT", 20)

# EVE type IDs of moon drilling refineries (Athanor, Tatara)
MOONDIST_REFINERY_TYPE_IDS = getattr(settings, "MOONDIST_REFINERY_TYPE_IDS", [35835, 35836])
