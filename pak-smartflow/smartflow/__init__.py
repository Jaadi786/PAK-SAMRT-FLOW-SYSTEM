"""Pak-SmartFlow -- from challan generation to compliance resolution.

A working reference prototype, not a slide deck. Runs on a bare Python 3.10+
install with zero third-party dependencies.

    python -m smartflow demo 4

Public API
----------
``run_scenario`` / ``run_all``   execute a demo scenario end to end
``FuzzyRiskEngine``              explainable Mamdani risk scoring
``decide``                       score -> action, with the safety overlay
``seal_evidence``                tamper-evident chain of custody
``compute_penalty``              progressive, capped, explainable late fees
``build_profile``                compliance scoring
``prepare_enforcement_request``  draft a packet for human authority review
``legal``                        the enforced boundary of what this never does
"""

from __future__ import annotations

__version__ = "0.3.0"
__all__ = [
    "AGENTS",
    "AGENT_COUNT",
    "DEFAULT_ENGINE",
    "DEFAULT_POLICY",
    "FuzzyRiskEngine",
    "PolicyConfig",
    "SCENARIOS",
    "Store",
    "build_profile",
    "compute_penalty",
    "decide",
    "evaluate_risk",
    "get_scenario",
    "run_all",
    "run_scenario",
    "seal_evidence",
    "verify_bundle",
    "__version__",
]

from .agents import AGENTS, AGENT_COUNT
from .compliance import build_profile, prepare_enforcement_request
from .config import DEFAULT_POLICY, PolicyConfig
from .db import Store
from .decision import decide
from .evidence import seal_evidence, verify_bundle
from .fuzzy import DEFAULT_ENGINE, FuzzyRiskEngine, evaluate_risk
from .penalty import compute_penalty
from .pipeline import run_all, run_scenario
from .scenarios import SCENARIOS, get_scenario
