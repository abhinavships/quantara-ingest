import os
import pytest
from quantara_core import crypto
from sim.runner import Rig
from edge.agent import Agent, chash
from sim.runner import ids_model


def test_sandbox_guard():
    with pytest.raises(PermissionError):
        Agent("R1", False, lambda m: None, ids_model(), "x", env={"SANDBOX": "1"})
    Agent("R1", False, lambda m: None, ids_model(), "x", env={})   # guard only when SANDBOX=1
    Agent("S1", True, lambda m: None, ids_model(), "x", env={"SANDBOX": "1"})


def test_clean_run_no_incidents():
    r = Rig().run(600)
    assert r.agent.records == [] and not r.kinds("escalation") and r.v.T < 45


def test_pump_failure_bounded():
    r = Rig()
    r.run(120, demand=1.0)
    r.v.flow_fault = 0.0
    r.run(1500)
    assert r.maxT < 60, r.maxT                       # critical limit is 58 C
    assert r.v.power_cap >= 0.4
    esc = r.kinds("escalation")
    assert esc and "unresolved" in esc[0]["reasons"]  # fault persists => local action cannot clear it
    assert esc[0]["freeze_frame"]["onset_chain"] and esc[0]["incident"]["cause"] == "pump_fault"


def test_faulty_sensor_does_not_cut_power():
    for fault in (("stuck", 20.0), ("offset", -15.0), ("offset", 40.0)):
        r = Rig().run(60)
        r.v.temp_sensor = fault
        r.run(300)
        assert "temp" in r.agent.ctl.ignored, fault
        assert r.agent.ctl.power_cap == 1.0 and r.v.power_cap == 1.0, fault


def test_calibration_tamper_restored_and_escalated():
    r = Rig().run(10)
    r.v.cal["torque_limit"] = 3.0
    r.run(3)
    assert r.v.cal["torque_limit"] == 1.0
    sec = r.kinds("security")
    assert sec and sec[0]["incident"]["cause"] == "calibration_tamper"


def test_link_down_autonomy_then_flush_buffered():
    r = Rig()
    r.run(60, demand=1.0)
    r.agent.up.set_link(False)
    r.v.flow_fault = 0.0
    r.run(400)
    assert r.maxT < 60 and r.v.power_cap < 1.0       # acted alone with the link down
    n_before = len(r.out)
    assert r.agent.up.buf
    r.agent.up.set_link(True)
    flushed = r.out[n_before:]
    assert flushed and all(m.get("buffered") for m in flushed)
    assert any(m["kind"] == "escalation" for m in flushed)


def test_ota_rejections():
    r = Rig()
    ota, priv = r.agent.ota, r.priv
    mk = lambda **k: crypto.make_command(priv, **{"vehicle_id": "V1", "kind": "derate",
                                                  "params": {"limit": 0.6}, "counter": 1, **k})
    ok = mk(); assert ota.handle(ok) == (True, "ok")
    assert ota.handle(ok)[1] == "replayed counter"
    t = {**mk(counter=2), "params": {"limit": 1.0}}; assert ota.handle(t)[1] == "bad signature"
    assert ota.handle(mk(counter=3, ttl_s=-5))[1] == "expired"
    assert ota.handle(mk(counter=4, vehicle_id="V2"))[1] == "wrong vehicle"
    assert ota.handle(mk(counter=5, params={"limit": 0.1}))[1] == "out of guard range"
    assert ota.handle(mk(counter=6, kind="software", params={}))[1] == "consent missing"
    c = lambda n: {"decision": "approved", "counter": n, "vehicle_id": "V1"}
    assert ota.handle(mk(counter=7, kind="security_patch", params={}, consent=c(7)))[1] == "oem approval missing"
    assert ota.handle(mk(counter=8, kind="security_patch", params={}, consent=c(8),
                         oem_approval={"approved": True, "counter": 8}))[0]
    assert ota.handle(mk(counter=9, kind="software", params={}, consent={**c(9), "decision": "declined"}))[1] == "consent missing"
    assert ota.handle(mk(counter=10, kind="software", params={}, consent=c(99)))[1] == "consent missing"   # proof bound to counter
    bad_key = crypto.make_command(crypto.gen_keypair()[0], "V1", "derate", {"limit": 0.6}, 11)
    assert ota.handle(bad_key)[1] == "bad signature"
