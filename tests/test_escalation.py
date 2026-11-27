import copy
from argonaut_core import crypto
from edge.policy import decide, Policy
from edge.rulebook import DEFAULT
from sim.runner import Rig

LEARNED = {"id": "learned_hot_cells", "cause": "high_internal_resistance",
           "when": "heat_resid > 0.01 and flow_ratio > 0.8 and power_frac > 0.5 and temp > 38",
           "clear": "temp < 33 or power_frac < 0.3", "dwell": 2, "clear_hold": 8,
           "action": {"type": "derate", "value": 0.5}}


def non_tel(r): return [m for m in r.out if m["kind"] != "telemetry"]


def transient_pump(r, hold=150):
    r.run(60, demand=1.0); r.v.flow_fault = 0.15; r.run(hold); r.v.flow_fault = 1.0; r.run(300)


def hot_cells(r):
    r.run(40, demand=0.8); r.v.kgen_mult = 3; r.run(700)


def test_policy_pure_function():
    base = {"cause": "pump_fault", "confidence": 0.9, "status": "open"}
    assert decide(base) == (False, [])
    assert "unattributed" in decide({**base, "cause": "unknown"})[1]
    assert "low_confidence" in decide({**base, "confidence": 0.5})[1]
    assert "competing_causes" in decide({**base, "competing": True})[1]
    assert "unresolved" in decide({**base, "age_ticks": 500})[1]
    assert decide({**base, "age_ticks": 500, "status": "cleared"})[0] is False
    assert "recurring" in decide({**base, "recurrences_hr": 4})[1]
    assert "needs_consent_or_update" in decide({**base, "needs_consent": True})[1]
    assert "fleet_pattern" in decide({**base, "fleet_pattern": True})[1]
    assert "security" in decide({**base, "security": True})[1]
    assert "unattributed" in decide({**base, "novelty": 2.0})[1]


def test_known_resolved_fault_not_escalated_summary_only():
    r = Rig(); transient_pump(r)
    assert not r.kinds("escalation")
    s = r.kinds("summary")
    assert len(s) == 1 and s[0]["incident"]["outcome"] == "cleared" and s[0]["incident"]["cause"] == "pump_fault"
    assert "freeze_frame" not in s[0]


def test_unknown_fault_escalated_with_freeze_frame():
    r = Rig(); hot_cells(r)
    e = r.kinds("escalation")
    assert e and {"unattributed"} <= set(e[0]["reasons"])
    ff = e[0]["freeze_frame"]
    assert ff["ring_5min"] and ff["onset_chain"] and ff["rulebook_version"] == 1
    assert ff["calibration_ok"] is True and "stats" in ff and "edge_actions" in ff


def test_unresolved_fault_escalated():
    r = Rig(); r.run(120, demand=1.0); r.v.flow_fault = 0.0; r.run(600)
    e = r.kinds("escalation")
    assert e and "unresolved" in e[0]["reasons"] and e[0]["freeze_frame"]["edge_actions"]


def test_recurring_fault_escalated():
    r = Rig()
    for _ in range(5):
        transient_pump(r, hold=100)
    e = [m for m in r.kinds("escalation") if "recurring" in m["reasons"]]
    assert e and e[0]["freeze_frame"]
    assert len(r.kinds("summary")) >= 3            # the early occurrences were summaries only


def test_consent_needed_fix_escalated():
    r = Rig(); r.run(60); r.v.tyre_drag = 1.5; r.run(60)
    e = r.kinds("escalation")
    assert e and "needs_consent_or_update" in e[0]["reasons"] and e[0]["incident"]["cause"] == "efficiency_degradation"


def test_security_event_always_escalated_in_addition_to_local_action():
    r = Rig(); r.run(20); r.bus.attack = "fuzz"; r.run(6)
    s = r.kinds("security")
    assert s and "security" in s[0]["reasons"] and "isolate_can" in s[0]["incident"]["actions"]
    assert "body_can" in r.agent.ctl.isolated and s[0]["freeze_frame"]


def test_fleet_pattern_escalated():
    r = Rig(); r.v.soc = 0.3; r.external = {"grid_outage": True}; r.run(5)
    e = r.kinds("escalation"); assert e and "fleet_pattern" in e[0]["reasons"]


def test_counters_and_bytes():
    r = Rig(); transient_pump(r)                      # 1 edge-resolved
    r.v.tyre_drag = 1.5; r.run(60)                    # 1 escalated (consent)
    c = r.agent.counters()
    assert c["edge_resolved"] == 1 and c["escalated"] == 1 and c["resolved_ratio"] == 0.5
    assert c["bytes_saved"] > 0 and c["bytes_sent"] < c["bytes_baseline"]
    assert c["bytes_sent"] == sum(len(__import__("json").dumps(m, separators=(",", ":"))) for m in r.out)


def test_learning_loop_moves_case_to_edge():
    before = Rig(); hot_cells(before)
    assert before.kinds("escalation") and not before.kinds("summary")        # cloud-solved case today
    rb = copy.deepcopy(DEFAULT); rb["version"] = 2; rb["rules"].append(LEARNED)
    after = Rig(); ota = after.agent.ota
    cmd = lambda n, rbk, consent=True: crypto.make_command(
        after.priv, "V1", "rulebook_update", {"rulebook": rbk}, n,
        consent={"decision": "approved", "counter": n, "vehicle_id": "V1"} if consent else None)
    assert ota.handle(cmd(1, rb, consent=False))[1] == "consent missing"
    bad = copy.deepcopy(rb); bad["limits"]["critical"] = 70
    assert not ota.handle(cmd(2, bad))[0]                                    # guard refuses loosened limits
    assert ota.handle(cmd(3, rb))[0] and after.agent.eng.version == 2
    hot_cells(after)
    assert not after.kinds("escalation") and len(after.kinds("summary")) == 1
    assert after.agent.records[0]["cause"] == "high_internal_resistance" and after.maxT < 58
