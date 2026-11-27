"""Explicit escalation policy. Pure function: incident dict -> (escalate, reasons)."""
from dataclasses import dataclass


@dataclass
class Policy:
    novelty_thr: float = 1.0       # IDS/novelty score above this => cannot attribute
    conf_min: float = 0.7
    margin: float = 0.15           # competing causes within this margin
    unresolved_ticks: int = 120    # N (thermal time constant is minutes)
    recur_per_hour: int = 3        # K


def decide(inc: dict, p: Policy = Policy()):
    r = []
    if inc.get("cause") in (None, "unknown") or inc.get("novelty", 0) > p.novelty_thr:
        r.append("unattributed")
    if inc.get("confidence", 1) < p.conf_min: r.append("low_confidence")
    if inc.get("competing"): r.append("competing_causes")
    if inc.get("age_ticks", 0) > p.unresolved_ticks and inc.get("status") != "cleared": r.append("unresolved")
    if inc.get("recurrences_hr", 0) > p.recur_per_hour: r.append("recurring")
    if inc.get("needs_consent") or inc.get("needs_software") or inc.get("needs_rulebook"): r.append("needs_consent_or_update")
    if inc.get("fleet_pattern"): r.append("fleet_pattern")
    if inc.get("security"): r.append("security")
    return bool(r), r
