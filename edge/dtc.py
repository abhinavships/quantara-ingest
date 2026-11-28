"""On-vehicle diagnostic trouble code (DTC) and intrusion rules. Deterministic and reduce-only: the EDGE is rule based;
interpretation (why, who to call, what to tell the driver) is the cloud model's job.
Input is the `diag` side channel from the vehicle's ECUs / gateways (names below); expressions use the whitelisted evaluator."""
DEFAULTS = {"contactor_weld": 0, "dcdc_v": 13.8, "bms_alive": 1, "cell_spread_mv": 20, "obd_msgs": 0, "err_frames": 0,
            "tcu_unknown_conns": 0, "charger_proto_err": 0, "adas_disagree": 0.0, "speed": 0.0}

DTCS = [
    # --- faults: edge limits damage, flags service_required (cloud decides self-fix / service centre / roadside)
    {"dtc": "P0AA1", "cause": "contactor_stuck", "when": "contactor_weld > 0", "actions": ["derate=0.4", "limp", "alert"], "service_required": True},
    {"dtc": "P0A94", "cause": "dcdc_converter_fault", "when": "dcdc_v < 12.0", "actions": ["derate=0.7", "alert"], "service_required": True},
    {"dtc": "U0111", "cause": "bms_comm_lost", "when": "bms_alive < 1", "actions": ["derate=0.4", "limp", "alert"], "service_required": True},
    {"dtc": "P0A80", "cause": "battery_degraded", "when": "cell_spread_mv > 150", "actions": ["derate=0.7", "alert"], "service_required": True},
    # --- intrusion: edge isolates the surface, cloud traces/correlates/patches
    {"dtc": "SEC-OBD", "cause": "obd_dongle", "when": "obd_msgs > 0 and speed > 5", "actions": ["isolate_obd", "alert"], "security": True},
    {"dtc": "SEC-BUSOFF", "cause": "ecu_impersonation", "when": "err_frames > 20", "actions": ["isolate_can", "alert"], "security": True},
    {"dtc": "SEC-TCU", "cause": "tcu_intrusion", "when": "tcu_unknown_conns > 0", "actions": ["isolate_tcu", "alert"], "security": True},
    {"dtc": "SEC-CHG", "cause": "rogue_charger", "when": "charger_proto_err > 0", "actions": ["stop_charge", "isolate_charger", "alert"], "security": True},
    {"dtc": "SEC-ADAS", "cause": "adas_spoofing", "when": "adas_disagree > 0.6", "actions": ["downweight_adas", "alert"], "security": True},
]
DWELL, CLEAR_HOLD = 2, 5
