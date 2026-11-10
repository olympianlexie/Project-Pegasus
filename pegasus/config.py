"""Project Pegasus settings. Edit the values in this file to change how a run behaves.

Every rebuild (``python -m pegasus.run``) reads this file, so a change here
takes effect on the next run. Values marked CONFIRMED were agreed with OSP
planning on 2026-11-10; change them only on purpose.
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Relocation planner (the settings people most often tune)
# --------------------------------------------------------------------------

# Farthest a Low NAP may be moved, measured from where it is now to the
# target pole. CONFIRMED: 500 m.
MAX_RELOCATION_M = 500

# Fiber rule. CONFIRMED (option a): a relocated NAP stays on its own LCP and
# PON; its cable is re-routed or extended. So the PON does not change and no
# splitter leg is needed at the target.
#
# TARGET_SCOPE limits which hotspots a candidate may be sent to:
#   "same_olt" - target NAP must be on the candidate's OLT (default)
#   "same_lcp" - target NAP must be on the candidate's LCP (strictest)
#   "any"      - no OLT/LCP restriction, distance only
TARGET_SCOPE = "same_olt"
# Among the allowed targets, prefer one on the candidate's own LCP.
PREFER_SAME_LCP = True

# Skip Low NAPs that were RFS'd recently: new areas need time to fill up.
# CONFIRMED: 12 months, counted back from the run date (or RFS_REFERENCE_DATE).
NEW_NAP_EXCLUSION_MONTHS = 12
RFS_REFERENCE_DATE = None  # None = today; or "2026-11-10"

# Candidates with 1-2 used ports have subscribers who must be moved to
# another NAP before the move. Require a nearby NAP with enough AVAILABLE
# ports to take them (it must not itself be relocated).
REQUIRE_SUBSCRIBER_REHOME = True
REHOME_MAX_M = 150          # drop-cable reach for re-homing subscribers
REHOME_SAME_LCP_ONLY = True  # keep re-homed subscribers on the same PON

# Demand hotspots: Risk and High NAPs grouped with DBSCAN.
HOTSPOT_EPS_M = 150          # neighbours within this distance join a hotspot
HOTSPOT_MIN_NAPS = 3         # fewer NAPs than this = not a hotspot ...
INCLUDE_SINGLE_NAP_HOTSPOTS = True  # ... unless this is True (then 1-2 NAP groups count too)
HOTSPOT_MAX_RADIUS_M = 400   # larger DBSCAN groups are split into sub-hotspots

# How many relocated NAPs a hotspot can take (CONFIRMED). Demand = the ports
# needed to bring every Risk/High NAP in the hotspot down to this many used
# ports (4 = top of Optimal), divided by the ports on one NAP, rounded up.
HOTSPOT_RELIEF_TARGET_USED = 4

# Do not stack many relocated NAPs on one pole.
MAX_NEW_NAPS_PER_TARGET_POLE = 2

# A target on the same pole/coordinate as the candidate is not a relocation.
SAME_POLE_TOLERANCE_M = 1.0

# Drop-cable reach: a subscriber can be connected to any NAP within this
# distance. A Low NAP with Risk/High demand closer than this is already
# positioned at demand.
DROP_REACH_M = 150

# What to do with Low NAPs that already have Risk/High demand within
# DROP_REACH_M (in the current data that is most of them: idle and full NAPs
# are interleaved, often on the same pole):
#   "keep"     - don't move them; list them as "sell from existing NAP", and
#                count their idle ports as supply already serving that
#                hotspot (it then needs fewer relocated NAPs). Only Low NAPs
#                out of reach of any demand are relocated. (default)
#   "relocate" - treat them like any other candidate; only same-pole targets
#                are ignored. Many recommendations will then be short moves.
NEAR_DEMAND_RULE = "keep"

# Coordinates shared by more NAPs than this are treated as possible
# placeholders: flagged everywhere and left out of relocation (both as
# candidates and targets), since their distances can't be trusted.
STACK_FLAG_THRESHOLD = 4
EXCLUDE_PLACEHOLDER_STACKS_FROM_RELOCATION = True

# --------------------------------------------------------------------------
# Utilization definitions
# --------------------------------------------------------------------------

# Port statuses that count as "utilized" (can't be sold). CONFIRMED default:
# ACTIVE + ALLOCATED + RESERVED, which matches Tableau for 98.2% of NAPs.
# Use {"ACTIVE"} for active-only. Statuses are compared upper-case.
UTILIZED_STATUSES = {"ACTIVE", "ALLOCATED", "RESERVED"}
# Ports that can be sold right now.
SELLABLE_STATUSES = {"AVAILABLE"}

# NAP levels by share of ports utilized (for an 8-port NAP:
# Low 0-2, Optimal 3-4, High 5-6, Risk 7-8). Upper bounds are inclusive.
NAP_LEVEL_BOUNDS = [("Low", 0.25), ("Optimal", 0.50), ("High", 0.75), ("Risk", 1.00)]

# OLT levels by utilization rate (from Tableau): Low < 30%, Optimal 30-60%,
# High 60-80%, Risk > 80%. Each pair is (level, rate must be below / at most).
OLT_LEVEL_BOUNDS = [("Low", 0.30, "lt"), ("Optimal", 0.60, "lt"), ("High", 0.80, "le"), ("Risk", 1.00, "le")]

LEVELS = ["Low", "Optimal", "High", "Risk"]
LEVEL_COLORS = {"Risk": "#d62728", "High": "#ff8c00", "Optimal": "#2ca02c", "Low": "#1f6fd1"}

# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
BOUNDARY_DIR = ROOT / "boundaries"
CACHE_DIR = OUTPUT_DIR / ".cache"

# The newest file matching each pattern in DATA_DIR is used, unless a path is
# passed on the command line.
RAW_FILE_GLOB = "Raw*Port*Utilization*.xlsx"
TABLEAU_FILE_GLOB = "Network*Elements*Map*Tableau*.xlsx"

# Optional real OLT / LCP locations. CSV columns: Olt Id, Latitude, Longitude
# (or Lcp Id, Latitude, Longitude). Rows here override the approximate
# (centroid-of-its-NAPs) locations.
OLT_SITES_FILE = DATA_DIR / "olt_sites.csv"
LCP_SITES_FILE = DATA_DIR / "lcp_sites.csv"

# Barangay/municipality name fixes for matching raw names to PSGC polygons.
BARANGAY_ALIASES_FILE = BOUNDARY_DIR / "barangay_aliases.csv"

# A Tableau OLT ID is mapped to a raw OLT ID when at least this share of its
# NAPs are on that raw OLT (detects OLT renumbering between exports).
OLT_RENUMBER_MIN_SHARE = 0.90

# --------------------------------------------------------------------------
# Map
# --------------------------------------------------------------------------
MAP_CENTER = (14.27, 121.30)
MAP_START_ZOOM = 10
MAP_TITLE = "Project Pegasus: Laguna NAP/OLT utilization"
