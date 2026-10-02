"""The five demo scenarios.

Each scenario is a frozen spec: what the camera saw, what history the vehicle
already has, and whether the citizen pays or disputes. The pipeline turns a
spec into a full case file, so the demo is reproducible rather than a
hand-waved screen recording.

Scenarios are chosen to cover the whole argument of the project:

1. An ordinary violation -- does the boring path work?
2. A dangerous combination -- does the safety overlay fire?
3. An emergency corridor -- does the system help instead of punish?
4. **The unpaid-challan loop** -- the differentiator: detect, challan, escalate,
   prepare for authority review, then resolve on payment.
5. A false positive and an appeal -- does the system admit its own mistakes?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from .integrations import AMBULANCE_PLATE
from .models import CameraEvent, FrameCapture, ViolationType


@dataclass(frozen=True)
class HistoryChallan:
    """A challan that already exists when the scenario begins."""

    violation: ViolationType
    age_days: int
    frames: int = 3
    witnesses: int = 3
    tamper: bool = False
    note: str = ""


@dataclass(frozen=True)
class ScenarioSpec:
    key: str
    number: int
    title: str
    subtitle: str
    plate: str
    camera_id: str
    location: str
    violations: tuple[ViolationType, ...]
    frames: int
    witnesses: int
    density: float
    context_tags: tuple[str, ...]
    speed_kmh: float | None = None
    speed_limit_kmh: float | None = None
    corridor: str = "Main corridor"
    history: tuple[HistoryChallan, ...] = ()
    notices_sent_prior: int = 0
    payment_attempts: int = 0
    disputes_open: int = 0
    pay_all: bool = False
    ambulance: bool = False
    ambulance_plate: str = AMBULANCE_PLATE
    ambulance_route: str = "Route B: Mall Road -> Jinnah Hospital"
    narrative: tuple[str, ...] = ()
    teaching_point: str = ""


# --------------------------------------------------------------------------- #
# Frame synthesis
# --------------------------------------------------------------------------- #
def synthesise_frames(
    count: int,
    witnesses: int,
    violation: ViolationType,
    camera_id: str,
    captured_at: datetime,
) -> tuple[FrameCapture, ...]:
    """Deterministic synthetic frames.

    Each payload begins with a verification header -- ``VF:<TYPE>:<0|1>`` --
    which stands in for a per-frame detector confidence. Everything after the
    ``|`` is filler whose only job is to make the SHA-256 digest unique per
    frame. Swapping in real JPEGs changes nothing downstream: the evidence
    layer only ever sees bytes.
    """
    if witnesses > count:
        raise ValueError("witness count cannot exceed frame count")
    frames: list[FrameCapture] = []
    for i in range(count):
        header = f"VF:{violation.value}:{1 if i < witnesses else 0}".encode("utf-8")
        filler = bytes((i * 37 + j * 7) % 256 for j in range(220))
        frames.append(
            FrameCapture(
                index=i,
                captured_at=captured_at + timedelta(milliseconds=250 * i),
                payload=header + b"|" + filler,
                camera_id=camera_id,
            )
        )
    return tuple(frames)


def build_event(spec: ScenarioSpec, as_of: datetime) -> CameraEvent:
    captured_at = as_of - timedelta(seconds=6)
    primary = spec.violations[0]
    return CameraEvent(
        camera_id=spec.camera_id,
        location=spec.location,
        captured_at=captured_at,
        violations=spec.violations,
        frames=synthesise_frames(
            spec.frames, spec.witnesses, primary, spec.camera_id, captured_at
        ),
        speed_kmh=spec.speed_kmh,
        speed_limit_kmh=spec.speed_limit_kmh,
        traffic_density=spec.density,
        context_tags=spec.context_tags,
    )


# --------------------------------------------------------------------------- #
# The scenarios
# --------------------------------------------------------------------------- #
SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        key="red_light",
        number=1,
        title="Ordinary violation, clean evidence",
        subtitle="Red-light running at a plain intersection during normal traffic.",
        plate="LEB-1234",
        camera_id="CAM-LHR-014",
        location="Ferozepur Road / Kalma Chowk, Lahore",
        violations=(ViolationType.RED_LIGHT,),
        frames=4,
        witnesses=4,
        density=55.0,
        context_tags=("INTERSECTION",),
        corridor="Ferozepur Road",
        narrative=(
            "4 of 4 frames witnessed the violation, so evidence confidence is high",
            "severity is high (red light) but collision exposure is ordinary",
            "expect a challan with a safety advisory, not an enforcement flag",
        ),
        teaching_point=(
            "The boring path has to work flawlessly, because it is 90% of real volume."
        ),
    ),
    ScenarioSpec(
        key="collision_risk",
        number=2,
        title="Dangerous combination near a school",
        subtitle="Wrong-way driving at 92 km/h in a 60 limit, school zone, rush hour, heavy traffic.",
        plate="LEB-7788",
        camera_id="CAM-LHR-027",
        location="Canal Road / School Zone, Lahore",
        violations=(ViolationType.WRONG_WAY, ViolationType.OVERSPEEDING),
        frames=4,
        witnesses=4,
        density=92.0,
        context_tags=("SCHOOL_ZONE", "RUSH_HOUR"),
        speed_kmh=92.0,
        speed_limit_kmh=60.0,
        corridor="Canal Road",
        narrative=(
            "wrong-way plus 53% over the limit, in dense traffic, outside a school",
            "expected: Safety Overlay promotes HIGH to CRITICAL",
            "a patrol hint and a signal review are recommended, not just a fine",
        ),
        teaching_point=(
            "A soft score cannot express 'this is about to kill someone'. A hard "
            "safety overlay can, and it says so out loud."
        ),
    ),
    ScenarioSpec(
        key="ambulance",
        number=3,
        title="Emergency corridor blocked",
        subtitle="A parked vehicle obstructs a hospital corridor while an ambulance is inbound.",
        plate="MUX-3312",
        camera_id="CAM-LHR-041",
        location="Hospital Corridor, Multan Road",
        violations=(ViolationType.ILLEGAL_PARKING,),
        frames=3,
        witnesses=2,
        density=90.0,
        context_tags=("HOSPITAL_ZONE",),
        corridor="Hospital corridor (Multan Road)",
        ambulance=True,
        ambulance_plate="AMB-0007",
        ambulance_route="Route B: Multan Road -> Jinnah Hospital",
        narrative=(
            "illegal parking is a low-severity violation on its own",
            "but it is blocking an ambulance corridor at 90% density",
            "expected: a proportionate challan PLUS a corridor clearance plan",
        ),
        teaching_point=(
            "Severity is not the same as harm. Context is what turns a parking "
            "ticket into an emergency-response problem."
        ),
    ),
    ScenarioSpec(
        key="unpaid_escalation",
        number=4,
        title="The unpaid-challan loop (the differentiator)",
        subtitle="Eight ignored challans, 127 days old, then a ninth violation today -- and a citizen who finally pays.",
        plate="RWP-9087",
        camera_id="CAM-RWP-006",
        location="Murree Road / Committee Chowk, Rawalpindi",
        violations=(ViolationType.RED_LIGHT,),
        frames=4,
        witnesses=4,
        density=60.0,
        context_tags=("INTERSECTION",),
        corridor="Murree Road",
        history=(
            HistoryChallan(ViolationType.RED_LIGHT, 127, note="Oldest unpaid case"),
            HistoryChallan(ViolationType.OVERSPEEDING, 120),
            HistoryChallan(ViolationType.WRONG_WAY, 110),
            HistoryChallan(ViolationType.RED_LIGHT, 98),
            HistoryChallan(ViolationType.OVERSPEEDING, 90),
            HistoryChallan(ViolationType.MOBILE_USE, 75),
            HistoryChallan(ViolationType.NO_HELMET, 60),
            HistoryChallan(ViolationType.RED_LIGHT, 45),
        ),
        pay_all=True,
        narrative=(
            "every existing system stops at 'challan issued' -- this one does not",
            "compliance history is scored, then the escalation ladder is reconstructed "
            "with historically correct timestamps",
            "an Enforcement Request is PREPARED for a human officer (two-key rule: "
            "elapsed time AND a low compliance score)",
            "the citizen then pays, and the request is withdrawn automatically",
        ),
        teaching_point=(
            "Recovery, not punishment. And every step is a notification or a "
            "recommendation -- never an action against the citizen."
        ),
    ),
    ScenarioSpec(
        key="false_positive_appeal",
        number=5,
        title="False positive and a citizen appeal",
        subtitle="Only 1 of 3 frames agrees, so no challan is issued -- and a previously issued challan fails evidence re-verification.",
        plate="LEB-1234",
        camera_id="CAM-LHR-014",
        location="Ferozepur Road / Kalma Chowk, Lahore",
        violations=(ViolationType.RED_LIGHT,),
        frames=3,
        witnesses=1,
        density=45.0,
        context_tags=("INTERSECTION",),
        corridor="Ferozepur Road",
        history=(
            HistoryChallan(
                ViolationType.RED_LIGHT,
                20,
                frames=3,
                witnesses=3,
                tamper=True,
                note="Evidence bundle corrupted after issuance (simulated)",
            ),
        ),
        narrative=(
            "1 of 3 frames agrees -> evidence confidence is below the gate",
            "expected: NO challan issued, case routed to a human reviewer",
            "the older challan's bundle fails re-verification -> penalty cancelled",
        ),
        teaching_point=(
            "An enforcement system that cannot admit error is not trustworthy. "
            "Here the machine cancels its own challan and says why."
        ),
    ),
)

SCENARIOS_BY_KEY: Mapping[str, ScenarioSpec] = {s.key: s for s in SCENARIOS}


def get_scenario(selector: str) -> ScenarioSpec:
    """Accept '4', 'unpaid_escalation', 'unpaid', or a unique fragment."""
    token = selector.strip().lower()
    if token in SCENARIOS_BY_KEY:
        return SCENARIOS_BY_KEY[token]
    if token.isdigit():
        number = int(token)
        for spec in SCENARIOS:
            if spec.number == number:
                return spec
        raise KeyError(f"no scenario numbered {number}")
    matches = [s for s in SCENARIOS if token in s.key or token in s.title.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise KeyError(f"unknown scenario {selector!r}")
    raise KeyError(f"ambiguous scenario {selector!r}: {[s.key for s in matches]}")


def all_scenarios() -> Sequence[ScenarioSpec]:
    return SCENARIOS
