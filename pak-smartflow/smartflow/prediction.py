"""Predictive-safety, emergency and optimisation heuristics.

These are transparent deterministic models, not trained networks. That is a
deliberate choice for a hackathon prototype: a judge can read the formula,
change an input and predict the output. Each function returns a dict that
documents its own assumptions, and each one names the drop-in replacement a
production build would use.

Replacement map
---------------
``estimate_collision_risk``  ->  LSTM trajectory model / TTC regression
``plan_ambulance_corridor``  ->  graph shortest-path with signal pre-emption
``optimise_signals``         ->  RL policy trained on the corridor's loop data
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CollisionEstimate:
    score: float
    time_to_collision_s: float
    speed_excess_pct: float
    components: Mapping[str, float]
    note: str


def estimate_collision_risk(
    speed_kmh: float | None,
    speed_limit_kmh: float | None,
    traffic_density: float,
    context_factor: float,
) -> CollisionEstimate:
    """Blend speed excess, congestion and location sensitivity into 0-100.

    Time-to-collision is a simplified kinematic proxy: the more the driver
    exceeds the limit and the denser the traffic, the less time an evasive
    action leaves. It is reported because seconds are easier to argue about in
    a safety briefing than an abstract score.
    """
    if speed_kmh is not None and speed_limit_kmh:
        excess_ratio = max(0.0, (speed_kmh - speed_limit_kmh) / max(1.0, speed_limit_kmh))
        speed_component = min(100.0, 40.0 + excess_ratio * 120.0)
    else:
        excess_ratio = 0.0
        speed_component = 45.0

    score = (
        0.50 * speed_component
        + 0.30 * max(0.0, min(100.0, traffic_density))
        + 0.20 * max(0.0, min(100.0, context_factor))
    )
    score = round(max(0.0, min(100.0, score)), 1)
    ttc = max(0.4, 3.5 - excess_ratio * 2.0 - (traffic_density / 100.0) * 1.2)
    return CollisionEstimate(
        score=score,
        time_to_collision_s=round(ttc, 2),
        speed_excess_pct=round(excess_ratio * 100.0, 1),
        components={
            "speed_component": round(speed_component, 1),
            "density_component": round(0.30 * traffic_density, 1),
            "context_component": round(0.20 * context_factor, 1),
        },
        note=(
            "Deterministic proxy model. Production: LSTM trajectory prediction "
            "per approach lane, calibrated against crash history."
        ),
    )


def plan_ambulance_corridor(
    ambulance_plate: str,
    route: str,
    traffic_density: float,
    junction_count: int = 4,
) -> Mapping[str, object]:
    """Recommend a clearance plan for an active emergency vehicle."""
    density = max(0.0, min(100.0, traffic_density))
    clearance_seconds = round(20 + density * 0.9 + junction_count * 4, 0)
    preemptions = [
        {
            "junction": f"J{i + 1}",
            "action": "hold conflicting phases, give green to the emergency axis",
            "lead_time_s": int(25 + i * 5),
        }
        for i in range(junction_count)
    ]
    return {
        "ambulance_plate": ambulance_plate,
        "recommended_route": route,
        "estimated_corridor_clearance_s": clearance_seconds,
        "signal_preemptions": preemptions,
        "civilian_action": (
            "Notify vehicles on the corridor to yield via variable message signs "
            "and the citizen app; do NOT issue challans for yielding manoeuvres "
            "made to clear the corridor."
        ),
        "note": (
            "Advisory only. Signal pre-emption requires the traffic-control "
            "authority's own command channel and a human operator."
        ),
    }


def optimise_signals(
    traffic_density: float,
    serious_violations: int,
    emergency_active: bool = False,
    corridor: str = "Main corridor",
) -> Mapping[str, object]:
    """Suggestion for adaptive green-time allocation on one corridor."""
    density = max(0.0, min(100.0, traffic_density))
    base_green = 35
    extra_green = int(density / 100.0 * 35)
    green = base_green + extra_green
    if emergency_active:
        green = max(20, green - 15)
    safety_hold = serious_violations >= 3
    return {
        "corridor": corridor,
        "cycle_seconds": 120,
        "proposed_green_seconds": green,
        "pedestrian_phase_seconds": 18,
        "safety_hold": safety_hold,
        "rationale": (
            f"Density {density:.0f} supports a {green}s green phase; "
            + (
                "emergency pre-emption reduces civilian green time. "
                if emergency_active
                else ""
            )
            + (
                f"{serious_violations} serious violations this window -> hold the "
                "phase plan and request a physical enforcement presence."
                if safety_hold
                else "No safety hold required this window."
            )
        ),
        "note": (
            "Advisory output. Signal changes are executed by the traffic-control "
            "authority, never by this prototype."
        ),
    }


def summarise_violation_mix(violations: Sequence[str]) -> Mapping[str, int]:
    mix: dict[str, int] = {}
    for name in violations:
        mix[name] = mix.get(name, 0) + 1
    return dict(sorted(mix.items(), key=lambda kv: kv[1], reverse=True))
