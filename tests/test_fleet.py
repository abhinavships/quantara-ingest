from quantara_core import crypto
from quantara_core.bus import MemBus
from sim.fleet import Fleet

FALLBACK = [[(12.9 + i * 1e-3, 77.5 + i * 1e-3) for i in range(40)]]


def mk(n=6):
    priv, pub = crypto.gen_keypair()
    return Fleet(n, MemBus(), pub, priv, routes=FALLBACK), priv


def collect(f, n):
    out = []
    for _ in range(n): out += f.step()
    return out


def test_clean_fleet_only_telemetry_and_modest_rate():
    f, _ = mk(); out = collect(f, 100)
    assert {m["kind"] for m in out} == {"telemetry"} and len(out) == 6 * 20   # 1 msg / 5 s / vehicle
    assert all(m["sim"] and "lat" in m for m in out)


def test_breakdown_scenario_escalates_from_target_only():
    f, _ = mk(); collect(f, 30); f.inject("breakdown", ["V001"]); out = collect(f, 700)
    esc = [m for m in out if m["kind"] == "escalation"]
    assert esc and {m["vehicle_id"] for m in esc} == {"V001"}


def test_grid_outage_escalates_fleet_pattern():
    f, _ = mk(); f.inject("grid_outage"); out = collect(f, 10)
    got = {m["vehicle_id"] for m in out if m["kind"] == "escalation" and "fleet_pattern" in m["reasons"]}
    assert got == set(f.rigs)
    assert not f.grid.snapshot(0)["stations"][0]["online"]


def test_cyber_and_degradation():
    f, _ = mk(); collect(f, 30)
    f.inject("cyber_flood", ["V000"]); f.inject("cal_tamper", ["V002"]); f.inject("degradation", ["V003"])
    out = collect(f, 120)
    sec = {m["vehicle_id"]: m["incident"]["cause"] for m in out if m["kind"] == "security"}
    assert sec["V000"].startswith("can_attack") and sec["V002"] == "calibration_tamper"
    assert any(m["vehicle_id"] == "V003" and m["kind"] == "escalation" for m in out)


def test_command_delivery_and_rejection():
    f, priv = mk()
    ok = f.deliver(crypto.make_command(priv, "V001", "derate", {"limit": 0.6}, 1))
    assert ok["ok"] and f.rigs["V001"].agent.ctl.cloud_cap == 0.6
    bad = f.deliver(crypto.make_command(priv, "V002", "derate", {"limit": 0.1}, 1))
    assert not bad["ok"] and bad["why"] == "out of guard range"
    assert not f.deliver({"vehicle_id": "NOPE"})["ok"]


def test_telemetry_mismatch_is_visible_in_uplink():
    f, _ = mk(); f.inject("telemetry_mismatch", ["V000"]); collect(f, 20)
    m = [x for x in collect(f, 10) if x["vehicle_id"] == "V000" and x["kind"] == "telemetry"][0]
    assert m["signals"]["Battery.Temp"] < 20          # physically impossible vs the ~30C pack
