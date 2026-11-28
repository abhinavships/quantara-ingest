"""DTC / intrusion faults: edge detects deterministically, acts reduce-only, escalates with the DTC code, clears when the fault goes."""
import pytest
from sim.fleet import DIAG_FAULTS
from sim.runner import Rig

CASES = {"contactor_stuck": ("P0AA1", False), "dcdc_fail": ("P0A94", False), "bms_comm_lost": ("U0111", False),
         "battery_degraded": ("P0A80", False), "obd_dongle": ("SEC-OBD", True), "ecu_busoff": ("SEC-BUSOFF", True),
         "tcu_intrusion": ("SEC-TCU", True), "rogue_charger": ("SEC-CHG", True), "adas_spoof": ("SEC-ADAS", True)}


@pytest.mark.parametrize("scenario", CASES)
def test_fault_detected_escalated_and_cleared(scenario):
    dtc, sec = CASES[scenario]
    r = Rig("V9", 3); r.run(30)
    assert not r.kinds("escalation") and not r.kinds("security")        # quiet baseline
    r.diag.update(DIAG_FAULTS[scenario]); r.run(8)
    m = (r.kinds("security") if sec else r.kinds("escalation"))[-1]
    assert m["incident"]["evidence"]["dtc"] == dtc
    assert m["incident"]["actions"]                                    # edge acted before the cloud heard
    r.diag.clear(); r.run(12)
    assert not r.agent.inc and not r.agent.ctl.dtc_caps                # cleared, limits released


def test_derate_is_reduce_only_and_floored():
    r = Rig("V9", 3); r.run(30); r.diag.update(DIAG_FAULTS["contactor_stuck"]); r.run(8)
    assert 0.4 <= r.agent.ctl.power_cap < 1.0 and r.v.speed_cap < 1.0


def test_vehicle_without_diag_is_untouched():
    r = Rig("V9", 3); r.run(60)
    assert not r.agent.inc and r.agent.ctl.power_cap == 1.0
