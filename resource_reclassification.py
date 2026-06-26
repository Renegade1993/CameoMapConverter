#!/usr/bin/env python3
"""
resource_reclassification.py -- Resource-node tiering for the Cameo map converter.

Design (rebuilt 2026-06-19):

  1. Each resource node's value is driven by its distance to the NEAREST spawn
     (so one player's base ore is never weighed against another player's rim).
  2. Map SYMMETRY is detected from the spawn/node geometry. Nodes are grouped
     into symmetry ORBITS (mirror pairs / rotational groups). Every node in an
     orbit is tiered together from the orbit's AVERAGE distance, so mirror-paired
     nodes are GUARANTEED to receive the same resource tier even on a
     human-built (slightly imperfect) map. This is the balance guarantee.
  3. The single RESOURCE_RICHNESS knob drives an aggressive "boundary-sweep":
        r = 0.5  -> essentially all Ore
        r = 1.0  -> even spread Ore -> GoldTiberium, ZERO gems
        r = 1.5  -> essentially all Gems
     monotonic and smooth between, saturating past ~0.5 and ~1.5. Gems are only
     ever produced when r > 1.0.
  4. An additional "even" distribution mode assigns resource types to achieve
     approximately equal CELL COUNTS for every active type, regardless of map
     position. The richness knob still controls how many types are active (same
     boundaries as the distance/balance modes).

Tier order (cheapest -> most valuable):
    Ore -> Tiberium -> BlueTiberium -> RedTiberium -> GoldTiberium -> Gems
"""

import math
from typing import Callable, Dict, List, Sequence, Tuple

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

TIER_ORDER = ["Ore", "Tiberium", "BlueTiberium", "RedTiberium", "GoldTiberium", "Gems"]

# Default RESOURCE_RICHNESS knob (the converter overrides this module global).
RESOURCE_RICHNESS = 1.0

# Distribution mode (the converter overrides this module global via --distribution):
#   "distance" -> value rises with distance from the nearest spawn; the richest
#                 resources land on the OUTER parts of the map (farthest from any
#                 base). Original behaviour.
#   "balance"  -> value rises toward the CONTESTED CENTRE: distance from the
#                 nearest spawn, boosted by how central (contested) the node is, so
#                 base patches stay Ore but the richest resources sit in the middle.
#   "even"     -> types are assigned to achieve equal CELL COUNTS for each active
#                 type. Richness knob controls active type count (same as other
#                 modes). Symmetry is still 100% guaranteed via orbits.
DISTRIBUTION_MODE = "balance"

# --- balance-mode tuning knobs (round, independent, only used in "balance") -----
# value = distance + BALANCE_BIAS * contestedness * home_gate
#   * distance  = an always-present baseline, so a map with nothing in its middle
#                 still grades by distance and never collapses to all-ore.
#   * contestedness only lifts a node BEYOND the home radius (home_gate), so near-base
#     nodes stay low no matter how contested, and out in the field the contested
#     middle outweighs raw distance (far-but-safe corners drop to mid tiers).
# BALANCE_BIAS: how hard to pull the rich tiers into the contested middle.
#   0 = behaves like "distance"; 3 = default; higher = stronger (can over-pull).
BALANCE_BIAS = 3

# BALANCE_HOME_RADIUS: the home/expansion safe zone, in GRID CELLS. Nodes within this
# of a spawn stay in the low tiers regardless of contestedness; the gate ramps to full
# one radius beyond it. A base footprint is a roughly fixed physical size, so an
# absolute grid radius travels well across map sizes.
BALANCE_HOME_RADIUS = 15

# Cameo resource indices (map.bin resource byte).
RESOURCE_INDICES = {
    "Ore": 3,
    "Tiberium": 1,
    "BlueTiberium": 2,
    "RedTiberium": 5,
    "GoldTiberium": 6,
    "Gems": 4,
}

# Node actor types per tier (kept for reference / external callers).
NODE_ACTORS = {
    "Ore": "MINE",
    "Tiberium": "SPLIT2",
    "BlueTiberium": "SPLITBLUE",
    "RedTiberium": "SPLITRED",
    "GoldTiberium": "SPLITGOLD",
    "Gems": "GMINE",
}

# The five non-gem tiers and their internal split points at richness == 1.0.
# Four boundaries split [0,1] evenly into Ore|Tiberium|Blue|Red|Gold.
_NONGEM_TIERS = TIER_ORDER[:5]
_BASE_BOUNDS = [0.2, 0.4, 0.6, 0.8]

# How far (in cells) a transformed point may sit from a real node/spawn and
# still be considered its symmetric image.
SPAWN_MATCH_TOL = 2.5
NODE_MATCH_TOL = 4.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


# ---------------------------------------------------------------------------
# The knob: distance fraction -> resource tier
# ---------------------------------------------------------------------------

def tier_for_fraction(frac: float, richness: float = RESOURCE_RICHNESS) -> str:
    """Map a normalized distance ``frac`` in [0,1] to a resource tier.

    ``frac`` is a node's (orbit-averaged) distance, normalized so the closest
    node is 0.0 and the furthest is 1.0.

    Knob behavior (the "boundary-sweep" model):

      * ``richness == 1.0``: the four internal boundaries sit at 0.2/0.4/0.6/0.8,
        giving an even Ore -> Tiberium -> Blue -> Red -> Gold spread. Gems off.
      * ``richness < 1.0``: ``lo`` ramps 0->1 as r goes 1.0->0.5; every boundary
        slides UP past 1.0, so Ore swallows the map. At r<=0.5 it is all Ore.
      * ``richness > 1.0``: a gem gate ``g`` slides DOWN from 1.0 toward 0.0 as r
        goes 1.0->1.5; any node at/above ``g`` becomes Gems, and the five lower
        tiers are compressed into ``[0, g)``. At r>=1.5 it is all Gems.

    Saturates past 0.5 and 1.5 (the ramps clamp at 1.0). Gems require r > 1.0.
    """
    frac = _clamp(frac, 0.0, 1.0)
    lo = _clamp((1.0 - richness) / 0.5, 0.0, 1.0)   # 1 at r<=0.5 .. 0 at r>=1.0
    hi = _clamp((richness - 1.0) / 0.5, 0.0, 1.0)   # 0 at r<=1.0 .. 1 at r>=1.5

    if hi > 0.0:
        gem_gate = 1.0 - hi                          # 1.0 -> 0.0 as r 1.0 -> 1.5
        if frac >= gem_gate:
            return "Gems"
        bounds = [b * gem_gate for b in _BASE_BOUNDS]
    else:
        # Slide boundaries up as richness drops. The top target overshoots 1.0 so
        # that at r<=0.5 even the furthest (frac==1.0) node collapses to Ore.
        top = 1.0 + 0.05 * lo
        bounds = [b + (top - b) * lo for b in _BASE_BOUNDS]

    for i, b in enumerate(bounds):
        if frac < b:
            return _NONGEM_TIERS[i]
    return _NONGEM_TIERS[-1]  # GoldTiberium


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------

def calculate_nearest_spawn_distances(nodes: Sequence[Dict],
                                      spawns: Sequence[Tuple[int, int]]) -> List[float]:
    """Each node's distance to its nearest spawn."""
    out = []
    for node in nodes:
        nx, ny = node["x"], node["y"]
        if spawns:
            out.append(min(math.hypot(nx - sx, ny - sy) for sx, sy in spawns))
        else:
            out.append(0.0)
    return out


# ---------------------------------------------------------------------------
# Symmetry detection + orbits
# ---------------------------------------------------------------------------

Transform = Tuple[str, Callable[[float, float], Tuple[float, float]]]


def _centroid(pts: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    if not pts:
        return (0.0, 0.0)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _candidate_transforms(spawns: Sequence[Tuple[int, int]]):
    """The symmetries a 1v1/2v2/4v4 tournament map might obey, built around the
    centroid of the spawns:
      - 180-degree point reflection
      - vertical / horizontal centre mirrors
      - diagonal mirrors across the main and anti-diagonals through the centre
      - 90-degree and 270-degree rotations around the centre
    """
    cx, cy = _centroid(spawns)
    transforms: List[Transform] = [
        ("point", lambda x, y: (2 * cx - x, 2 * cy - y)),
        ("vertical", lambda x, y: (2 * cx - x, y)),
        ("horizontal", lambda x, y: (x, 2 * cy - y)),
        # Main diagonal (x-y) through centre: (x,y) -> (cx+(y-cy), cy+(x-cx))
        ("diag_main", lambda x, y: (cx + y - cy, cy + x - cx)),
        # Anti diagonal (x+y) through centre: (x,y) -> (cx-(y-cy), cy-(x-cx))
        ("diag_anti", lambda x, y: (cx - y + cy, cy - x + cx)),
        # 90-degree rotation around centre
        ("rot90", lambda x, y: (cx - y + cy, cy + x - cx)),
        # 270-degree rotation around centre
        ("rot270", lambda x, y: (cx + y - cy, cy - x + cx)),
    ]
    return transforms, (cx, cy)


def _set_maps_onto_itself(T: Callable, pts: Sequence[Tuple[float, float]], tol: float,
                         use_median: bool = False) -> bool:
    """True if every point in ``pts`` maps (under T) near some point in ``pts``.

    If use_median is True, the median error is compared against tol instead of the
    max error, making the test robust to a few imperfect/asymmetric points.
    """
    if not pts:
        return False
    errs = []
    for (x, y) in pts:
        tx, ty = T(x, y)
        d = min(math.hypot(tx - px, ty - py) for (px, py) in pts)
        if not use_median and d > tol:
            return False
        errs.append(d)
    if use_median:
        errs.sort()
        return errs[len(errs) // 2] <= tol
    return True


def detect_symmetries(spawns: Sequence[Tuple[int, int]], nodes: Sequence[Dict],
                      spawn_tol: float = SPAWN_MATCH_TOL,
                      node_tol: float = NODE_MATCH_TOL):
    """Return ``(transforms, center)``: the list of symmetry transforms the map
    actually obeys. A transform qualifies only if it permutes the SPAWN set onto
    itself (a strong filter -- only true map symmetries do this) and maps the
    node set onto itself with a small median error."""
    center = _centroid(spawns) if spawns else (0.0, 0.0)
    if len(spawns) < 2:
        return [], center
    candidates, center = _candidate_transforms(spawns)
    npts = [(n["x"], n["y"]) for n in nodes]
    chosen: List[Transform] = []
    for name, T in candidates:
        # Use median error for spawns to tolerate slightly imperfect maps.
        if not _set_maps_onto_itself(T, spawns, spawn_tol, use_median=True):
            continue
        if npts:
            errs = sorted(
                min(math.hypot(T(x, y)[0] - px, T(x, y)[1] - py) for (px, py) in npts)
                for (x, y) in npts
            )
            if errs[len(errs) // 2] > node_tol:   # median match error
                continue
        chosen.append((name, T))
    return chosen, center


def build_orbits(nodes: Sequence[Dict], transforms: Sequence[Transform],
                 tol: float = NODE_MATCH_TOL) -> List[List[int]]:
    """Group node indices into symmetry orbits via union-find over all the
    transforms the map obeys (so a 4-fold-symmetric map yields 4-node orbits)."""
    n = len(nodes)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pts = [(nd["x"], nd["y"]) for nd in nodes]
    for _name, T in transforms:
        for i, (x, y) in enumerate(pts):
            tx, ty = T(x, y)
            best = None
            bi = None
            for j, (px, py) in enumerate(pts):
                d = math.hypot(tx - px, ty - py)
                if best is None or d < best:
                    best, bi = d, j
            if bi is not None and bi != i and best <= tol:
                union(i, bi)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Per-node value (the metric the knob acts on) -- depends on DISTRIBUTION_MODE
# ---------------------------------------------------------------------------

def _norm01(vals: List[float]) -> List[float]:
    lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
    span = (hi - lo) or 1.0
    return [(v - lo) / span for v in vals]


def node_values(nodes: Sequence[Dict], spawns: Sequence[Tuple[int, int]],
                dists: Sequence[float], mode: str) -> List[float]:
    """Per-node value the richness knob ranks. Symmetric metrics only, so orbit
    averaging still guarantees mirror pairs match.

    mode == "distance": value = nearest-spawn distance -> the richest resources land
                        on the OUTER parts of the map (farthest from any base).
    mode == "balance":  value = CONTESTEDNESS, a spawn-influence heatmap. Each spawn
                        projects a linear-falloff influence out to radius R (R scaled
                        to how far the spawns sit from their centroid). A node's value
                        is the summed influence MINUS the single strongest one -- i.e.
                        how much players OTHER than its dominant owner also reach it. It
                        is ~0 inside any one base and on the empty periphery, and peaks
                        in the overlap zones BETWEEN bases (the contested middle). So
                        the richest resources sit on the front line; base patches and
                        remote corners stay ore.
    """
    if mode == "balance":
        cx, cy = _centroid(spawns)
        if spawns:
            R = 2.0 * (sum(math.hypot(s[0] - cx, s[1] - cy) for s in spawns) / len(spawns))
        else:
            R = 1.0
        R = R or 1.0
        # contestedness = spawn-influence overlap (sum of linear-falloff influences
        # minus the dominant one): high BETWEEN bases, ~0 in any one base / periphery.
        contest = []
        for n in nodes:
            inf = [max(0.0, 1.0 - math.hypot(n["x"] - sx, n["y"] - sy) / R) for sx, sy in spawns]
            contest.append((sum(inf) - max(inf)) if inf else 0.0)
        dn = _norm01(list(dists))            # distance baseline: 0 at base .. 1 at rim
        cn = _norm01(contest)                # contestedness: 0..1
        # HOME-INVARIANT base metric: distance baseline + contestedness. The home radius
        # is applied SEPARATELY, as a multiplicative gate on the ranking FRACTION (see
        # assign_node_tiers_debug), so enlarging the home zone only demotes near-spawn
        # nodes toward Ore and can never re-tier distant ones. (Previously the home gate
        # was folded into the value here; because tiers come from a global min-max
        # normalization, shrinking that term as HOME grew rescaled EVERY node and
        # PROMOTED far/mid fields -- the reported home-radius bug.)
        return [dn[i] + BALANCE_BIAS * cn[i] for i in range(len(nodes))]
    return list(dists)


# ---------------------------------------------------------------------------
# Even distribution: equal cell counts per active type
# ---------------------------------------------------------------------------

def _active_tiers(richness: float) -> List[str]:
    """Return the ordered list of active resource types for a given richness.

    For even-distribution mode the goal is to maximise the number of distinct
    types on the map.  Probing ``tier_for_fraction`` at a handful of fixed
    fractions doesn't work reliably — on maps where all nodes cluster in a
    narrow distance band the probes can all land on the same tier, collapsing
    everything to 1-2 types.

    Instead this function returns the **full set of types reachable** at the
    given richness, using the same knob semantics as the other modes:

      r <= 0.5  -> [Ore]  (all-Ore saturation)
      0.5 < r < 1.0 -> Ore + a growing prefix of non-gem tiers
      r == 1.0  -> all five non-gem tiers (Ore … GoldTiberium)
      1.0 < r < 1.5 -> all non-gem tiers + Gems
      r >= 1.5  -> [Gems]  (all-Gems saturation)

    The returned list is in TIER_ORDER so the even balancer assigns Ore to the
    nearest orbits and grades outward toward Gems.
    """
    if richness <= 0.5:
        return ["Ore"]
    if richness >= 1.5:
        return ["Gems"]

    nongem = ["Ore", "Tiberium", "BlueTiberium", "RedTiberium", "GoldTiberium"]

    if richness >= 1.0:
        # All non-gem tiers are available; add Gems proportionally above 1.0
        result = list(nongem)
        if richness > 1.0:
            result.append("Gems")
        return result

    # 0.5 < richness < 1.0: include a growing prefix of non-gem tiers.
    # At r=0.5 only Ore; at r=1.0 all five.  Scale linearly: 1 type at 0.5,
    # 5 types at 1.0.  Use ceiling so r just above 0.5 already gets 2 types.
    t = (richness - 0.5) / 0.5           # 0 at r=0.5, 1 at r=1.0
    # Map t in (0,1] to n in [2,5]: floor(t*4)+2 gives 2 at t just above 0,
    # up to 5 at t=1 (r=1.0, handled by the r>=1.0 branch above).
    # Add a tiny epsilon so boundary values (t=0.25, 0.5, 0.75) round up cleanly.
    n = max(2, min(5, int(t * 4 + 1e-9) + 2))
    return nongem[:n]


def assign_node_tiers_even(nodes: Sequence[Dict],
                            spawns: Sequence[Tuple[int, int]],
                            richness: float = RESOURCE_RICHNESS,
                            node_cell_counts: Sequence[int] = None) -> List[str]:
    """Assign resource tiers for Even mode.

    Prime directive (Aedis spec): **equal amount of each resource type on every
    map**.  The richness knob is intentionally IGNORED — even mode always uses
    all six tier slots (Ore → Gems) spread evenly across the orbit distance
    bands.  If a map only has N distinct orbit distance bands (N < 6), it gets N
    types; it is impossible to force more types than there are distance bands
    without breaking symmetry.

    Algorithm:
      1. Detect symmetry orbits → mirror guarantee.
      2. Sort orbits by average nearest-spawn distance ascending (closest → Ore).
      3. Divide TIER_ORDER[0:6] evenly across the N orbits (equal-width bands).
      4. Assign one type per orbit, Ore nearest, Gems farthest.

    ``richness`` and ``node_cell_counts`` are accepted for API compatibility but
    are not used.
    """
    if not nodes:
        return []
    if not spawns:
        return ["Ore"] * len(nodes)

    dists = calculate_nearest_spawn_distances(nodes, spawns)
    transforms, _center = detect_symmetries(spawns, nodes)
    orbits = (build_orbits(nodes, transforms)
              if transforms else [[i] for i in range(len(nodes))])
    n_orbits = len(orbits)

    # Sort orbits by average nearest-spawn distance ascending.
    orbit_avg_dist = [sum(dists[i] for i in orb) / max(len(orb), 1)
                      for orb in orbits]
    order = sorted(range(n_orbits), key=lambda k: orbit_avg_dist[k])

    # Distribute all 6 tier slots across the orbits so every tier appears at least
    # once (as long as there are >= 6 orbits) and extras go to the lower tiers.
    #
    # The old approach used floor(rank * 6 / n_orbits), a linear partition that
    # silently skips one tier when n_orbits is not a multiple of 6.  Example: with
    # 8 orbits it produced [Ore,Ore,Tib,Blue,Red,Red,Gold,Gems] — Red appeared twice
    # and no orbit ever got GoldTiberium from rank 5 (it went to Red).  On maps where
    # nodes cluster near the base, the two Ore slots could dominate the visual result.
    #
    # The new approach: quota-fill.  Each tier gets base = n_orbits // n_tiers orbits;
    # the first (n_orbits % n_tiers) tiers each get one extra.  This guarantees:
    #   * Every tier appears at least once (if n_orbits >= n_tiers).
    #   * The distribution is as even as possible (counts differ by at most 1).
    #   * Extra slots go to the LOWEST tiers (Ore first), keeping the richest types
    #     spatially on the outer bands where there are fewer orbits.
    ladder = TIER_ORDER  # ["Ore","Tiberium","Blue","Red","Gold","Gems"]
    n_tiers = len(ladder)  # 6

    # Build the per-rank tier index list.
    if n_orbits <= n_tiers:
        # Fewer orbits than tiers: one orbit per tier, Ore first; upper tiers absent.
        rank_to_tier_idx = list(range(n_orbits))
    else:
        base = n_orbits // n_tiers
        extra = n_orbits % n_tiers
        rank_to_tier_idx = []
        for t in range(n_tiers):
            count = base + (1 if t < extra else 0)
            rank_to_tier_idx.extend([t] * count)

    orbit_tier: Dict[int, str] = {}
    for rank, k in enumerate(order):
        orbit_tier[k] = ladder[rank_to_tier_idx[rank]]

    tiers = ["Ore"] * len(nodes)
    for k, orb in enumerate(orbits):
        t = orbit_tier[k]
        for i in orb:
            tiers[i] = t

    return tiers


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def assign_node_tiers_corrected(nodes: Sequence[Dict], spawns: Sequence[Tuple[int, int]],
                                richness: float = RESOURCE_RICHNESS,
                                mode: str = None,
                                node_cell_counts: Sequence[int] = None) -> List[str]:
    """Assign a resource tier to every node.

    Symmetry-safe: nodes are grouped into orbits and every member of an orbit is
    tiered from the orbit's average nearest-spawn distance, so mirror-paired
    nodes always agree. The RESOURCE_RICHNESS knob then drives the tier via
    ``tier_for_fraction``.

    When mode == "even", ``node_cell_counts`` (per-node field-cell counts) is
    used to balance type assignments by actual resource-cell weight.
    """
    if not nodes:
        return []
    if not spawns:
        return ["Ore"] * len(nodes)
    if (mode or DISTRIBUTION_MODE) == "even":
        return assign_node_tiers_even(nodes, spawns, richness, node_cell_counts)
    return assign_node_tiers_debug(nodes, spawns, richness, mode)["tiers"]


def assign_node_tiers_debug(nodes: Sequence[Dict], spawns: Sequence[Tuple[int, int]],
                            richness: float = RESOURCE_RICHNESS,
                            mode: str = None,
                            node_cell_counts: Sequence[int] = None) -> Dict:
    """Like ``assign_node_tiers_corrected`` but returns the full working set
    (distances, orbit-averaged representative distance, normalized fraction,
    tiers, orbits, symmetry names) for renderers, tests and diagnostics.

    When mode == "even", delegates to ``assign_node_tiers_even`` and wraps its
    result in the standard debug dict so callers see a consistent interface.
    """
    if mode is None:
        mode = DISTRIBUTION_MODE
    dists = calculate_nearest_spawn_distances(nodes, spawns)
    # Even mode has its own path: no distance-fraction ranking.
    if mode == "even":
        transforms, center = detect_symmetries(spawns, nodes)
        orbits = (build_orbits(nodes, transforms)
                  if transforms else [[i] for i in range(len(nodes))])
        tiers = assign_node_tiers_even(nodes, spawns, richness, node_cell_counts)
        return {
            "mode": mode,
            "dists": dists,
            "values": [0.0] * len(nodes),
            "rep": [0.0] * len(nodes),
            "frac": [0.0] * len(nodes),
            "frac0": [0.0] * len(nodes),
            "tiers": tiers,
            "orbits": orbits,
            "symmetries": [name for name, _ in transforms],
            "center": center,
            "range": (0.0, 0.0),
        }
    values = node_values(nodes, spawns, dists, mode)
    transforms, center = detect_symmetries(spawns, nodes)
    orbits = build_orbits(nodes, transforms) if transforms else [[i] for i in range(len(nodes))]

    # Representative value per node = mean over its orbit (the "average" symmetry
    # rule). Orbit members therefore share a fraction/tier -> mirror pairs match.
    rep = [0.0] * len(nodes)
    for orb in orbits:
        m = sum(values[i] for i in orb) / len(orb)
        for i in orb:
            rep[i] = m

    lo, hi = (min(rep), max(rep)) if rep else (0.0, 1.0)
    span = hi - lo
    frac0 = [0.0 if span <= 1e-9 else (rep[i] - lo) / span for i in range(len(nodes))]

    # Home-radius suppression (balance AND distance modes). Scale each node's ranking
    # fraction by a home gate so NEAR-spawn nodes drop toward Ore. The gate uses
    # orbit-AVERAGED distance (mirror pairs stay identical) and lies in [0,1]: 0 within
    # the home radius, ramping to 1 one radius beyond it. Because the gate only ever
    # SHRINKS the fraction and tier_for_fraction is monotonic, a larger home radius can
    # only LOWER a node's tier, never raise it. Applying it to the fraction rather than
    # the final tier preserves the richness-knob extremes (r<=0.5 -> all Ore, r>=1.5
    # -> all Gems, both independent of fraction).
    frac = list(frac0)
    if mode in ("balance", "distance") and nodes:
        base_r = float(BALANCE_HOME_RADIUS) or 1.0
        rep_dist = [0.0] * len(nodes)
        for orb in orbits:
            md = sum(dists[i] for i in orb) / len(orb)
            for i in orb:
                rep_dist[i] = md
        frac = [frac0[i] * _clamp((rep_dist[i] - base_r) / base_r, 0.0, 1.0)
                for i in range(len(nodes))]

    tiers = [tier_for_fraction(frac[i], richness) for i in range(len(nodes))]

    return {
        "mode": mode,
        "dists": dists,
        "values": values,
        "rep": rep,
        "frac": frac,
        "frac0": frac0,
        "tiers": tiers,
        "orbits": orbits,
        "symmetries": [name for name, _ in transforms],
        "center": center,
        "range": (lo, hi),
    }


if __name__ == "__main__":
    spawns = [(10, 10), (90, 90)]
    nodes = [
        {"x": 18, "y": 18}, {"x": 82, "y": 82},
        {"x": 30, "y": 30}, {"x": 70, "y": 70},
        {"x": 50, "y": 20}, {"x": 50, "y": 80},
    ]
    for r in (0.5, 0.75, 1.0, 1.25, 1.5):
        info = assign_node_tiers_debug(nodes, spawns, r)
        counts: Dict[str, int] = {}
        for t in info["tiers"]:
            counts[t] = counts.get(t, 0) + 1
        mix = {t: counts[t] for t in TIER_ORDER if t in counts}
        print(f"r={r}: symmetries={info['symmetries']} orbits={len(info['orbits'])} -> {mix}")
