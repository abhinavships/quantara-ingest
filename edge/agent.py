"""Edge agent: solve locally, escalate only what the policy says. No network needed to act."""
import hashlib
import json
import os
import time
from collections import deque

from .dtc import CLEAR_HOLD, DEFAULTS, DTCS, DWELL
from .evaluator import safe_eval
from .ids import Ids
from .ota import OtaClient
from .policy import Policy, decide
from .rulebook import Engine, DERATE_FLOOR
from .stats import Roll

NOM = 12.0
CLIP = lambda x, a=0.0, b=1.0: max(a, min(b, x))
J = lambda o: len(json.dumps(o, separators=(",", ":")))


def chash(cal): return hashlib.sha256(json.dumps(cal, sort_keys=True).encode()).hexdigest()


class Controller:
    """Reduce-only local actuators. Effective cap never below DERATE_FLOOR."""
    def __init__(self):
        self.edge_cap, self.cloud_cap, self.limp, self.edge_limp = 1.0, 1.0, 1.0, 1.0
        self.isolated, self.ignored, self.applied, self.hot = set(), set(), [], False
        self.dtc_caps, self.dtc_limp = {}, {}              # per-DTC reduce-only limits

    @property
    def power_cap(self): return max(DERATE_FLOOR, min(self.edge_cap, self.cloud_cap, *self.dtc_caps.values()))


class Uplink:
    """Store-and-forward. Escalations are kept preferentially when the buffer is full."""
    def __init__(self, publish, max_bytes=200_000):
        self.pub, self.up, self.buf, self.max, self.bytes = publish, True, deque(), max_bytes, 0
        self.sent_bytes, self.dropped = 0, 0

    def send(self, msg):
        if self.up and not self.buf:
            self.sent_bytes += J(msg); self.pub(msg); return
        self.buf.append(msg)
        while sum(J(m) for m in self.buf) > self.max:
            i = next((k for k, m in enumerate(self.buf) if m["kind"] == "telemetry"), 0)
            del self.buf[i]; self.dropped += 1

    def set_link(self, up):
        self.up = up
        while up and self.buf:
            m = self.buf.popleft(); m["buffered"] = True
            self.sent_bytes += J(m); self.pub(m)


class Agent:
    def __init__(self, vehicle_id, sim, publish, ids_model, pub_key, policy=None, rulebook=None,
                 golden_cal=None, tel_every=5, env=os.environ):
        if env.get("SANDBOX") == "1" and not sim:
            raise PermissionError("SANDBOX=1: refusing non-simulated vehicle")
        self.vid, self.sim, self.policy = vehicle_id, sim, policy or Policy()
        self.eng, self.ctl = Engine(rulebook), Controller()
        self.ota = OtaClient(vehicle_id, pub_key, self.ctl, self.eng)
        self.ids, self.up, self.tel_every = Ids(ids_model), Uplink(publish), tel_every
        self.golden = golden_cal; self.golden_hash = chash(golden_cal) if golden_cal else None
        self.roll = {k: Roll() for k in ("temp", "flow", "cur", "kpk")}
        self.ring, self.tick_n, self.t = deque(maxlen=300), 0, 0.0
        self.inc, self.records, self.hist = {}, [], {}
        self.n = {"resolved": 0, "escalated": 0, "baseline_bytes": 0, "inc_n": 0}
        self.est, self.est_ok, self.onset, self.heat_ewma = None, True, {}, 0.0
        self.kpk_base, self.last_temp = None, None
        self.cal_ok = True
        self.dtc_state = {d["dtc"]: {"on": 0, "off": 0} for d in DTCS}

    # ---------- helpers ----------
    def _est_step(self, P, flow, dt):
        from sim.vehicle import KGEN, KNAT, KFLOW, TAMB, C
        return self.est + dt * (KGEN * P * P - (KNAT + KFLOW * flow / NOM) * (self.est - TAMB)) / C

    def _mark(self, key, cond):
        if cond: self.onset.setdefault(key, self.tick_n)
        else: self.onset.pop(key, None)

    def _attribute(self, f):
        sc = {"pump_fault": CLIP((0.85 - f["flow_ratio"]) / 0.45),
              "high_load": 0.85 if f["flow_ratio"] >= 0.8 and f["power_frac"] >= 0.6 and f["heat_resid"] < 0.02 else 0.0}
        ranked = sorted(sc.items(), key=lambda kv: -kv[1])
        (c1, s1), (c2, s2) = ranked[0], ranked[1]
        if s1 < 0.5: return "unknown", s1, False
        return c1, s1, (s1 - s2) < self.policy.margin

    def _freeze(self, inc):
        stats = {k: {"mean": round(r.mean, 3), "std": round(r.std, 3), "slope": round(r.slope, 4),
                     "ewma": round(r.ewma or 0, 3)} for k, r in self.roll.items()}
        return {"ring_5min": list(self.ring)[::5], "onset_chain": sorted(
                    ({"tick": v, "event": k} for k, v in self.onset.items()), key=lambda x: x["tick"]),
                "stats": stats, "rulebook_version": self.eng.version, "calibration_ok": self.cal_ok,
                "edge_actions": inc["actions"], "ids_novelty": round(self.ids.novelty, 3)}

    def _open(self, key, cause, conf, evidence, actions, competing=False, **flags):
        hist = self.hist.setdefault(cause, [])
        hist[:] = [x for x in hist if self.t - x < 3600]
        inc = {"id": f"{self.vid}-{self.n['inc_n']}", "key": key, "cause": cause, "confidence": round(conf, 3),
               "competing": competing, "evidence": evidence, "actions": list(actions), "opened": self.tick_n,
               "status": "open", "escalated": False, "recurrences_hr": len(hist), "novelty": 0.0, **flags}
        hist.append(self.t); self.n["inc_n"] += 1; self.inc[key] = inc
        self._maybe_escalate(inc, "open")

    def _maybe_escalate(self, inc, why):
        if inc["escalated"]: return
        inc["age_ticks"] = self.tick_n - inc["opened"]
        esc, reasons = decide(inc, self.policy)
        if esc:
            inc["escalated"] = True; self.n["escalated"] += 1
            self.up.send({"kind": "security" if inc.get("security") else "escalation", "vehicle_id": self.vid,
                          "ts": self.t, "reasons": reasons, "incident": {k: inc[k] for k in
                          ("id", "cause", "confidence", "evidence", "actions", "status")},
                          "freeze_frame": self._freeze(inc)})

    def _close(self, key, outcome):
        inc = self.inc.pop(key)
        inc.update(status=outcome, closed=self.tick_n)
        self.records.append({k: inc[k] for k in ("id", "cause", "evidence", "actions", "confidence")} |
                            {"outcome": outcome, "escalated": inc["escalated"]})
        if not inc["escalated"]:
            self.n["resolved"] += 1
            self.up.send({"kind": "summary", "vehicle_id": self.vid, "ts": self.t, "incident": {
                "id": inc["id"], "cause": inc["cause"], "conf": inc["confidence"],
                "actions": inc["actions"], "outcome": outcome, "ticks": self.tick_n - inc["opened"]}})
        else:
            self.up.send({"kind": "summary", "vehicle_id": self.vid, "ts": self.t, "update": True,
                          "incident": {"id": inc["id"], "outcome": outcome}})

    # ---------- main tick ----------
    def tick(self, s: dict, frames=None, external=None, dt=1.0, cal=None):
        self.tick_n += 1; self.t += dt; external = external or {}
        self.n["baseline_bytes"] += J({"vehicle_id": self.vid, "ts": self.t, "signals": s})
        sig = dict(s); temp_raw = s["Battery.Temp"]
        flow, duty, P = s["Coolant.Flow"], s["Pump.Duty"], s["Power.kW"]
        # sensor plausibility: abrupt jump or flatline => ignore, run on model estimate
        r = self.roll["temp"]
        jump = self.last_temp is not None and abs(temp_raw - self.last_temp) > 4.0
        flat = len(r.w) >= 20 and r.std < 0.005 and P > 10 and self.tick_n > 25
        self.last_temp = temp_raw
        if self.est is None: self.est = temp_raw
        if "temp" not in self.ctl.ignored and (jump or flat):
            self.ctl.ignored.add("temp")
            self._open("sensor", "sensor_fault", 0.9, {"jump": jump, "flat": flat, "raw": temp_raw},
                       ["ignore_sensor"])
        self.est = self._est_step(P, flow, dt)
        if "temp" in self.ctl.ignored: temp = self.est       # fail-safe: model, never cut power on bad data
        else:
            self.est += 0.2 * (temp_raw - self.est); temp = temp_raw
        r.push(temp_raw); self.roll["flow"].push(flow); self.roll["cur"].push(s["Motor.Current"])
        self.roll["kpk"].push(s["Battery.kmPerKwh"])
        fr = CLIP(flow / (duty * NOM)) if duty > 0.05 else 1.0
        pred = (0.0005 * P * P - (0.05 + 0.25 * flow / NOM) * (temp - 25)) / 60
        meas_rate = r.rate if "temp" not in self.ctl.ignored else 0.0
        self.heat_ewma = 0.9 * self.heat_ewma + 0.1 * (meas_rate - pred)
        f = {"temp": temp, "flow_ratio": fr, "power_frac": P / 80, "heat_resid": self.heat_ewma,
             "temp_slope": r.slope, "temp_z": r.z(temp_raw), "kpkwh": s["Battery.kmPerKwh"], "soc": s["Battery.SoC"]}
        self.ctl.hot = temp > self.eng.rb["limits"]["warn"]
        self._mark("flow_drop", fr < 0.8); self._mark("temp_rising", r.slope > 0.01)
        self._mark("temp_over_warn", temp > self.eng.rb["limits"]["warn"])
        # rules
        fired, cleared, active = self.eng.step(f)
        caps = [a["action"]["value"] for a in active if a["action"]["type"] == "derate"]
        self.ctl.edge_cap = min(caps) if caps else 1.0
        self.ctl.edge_limp = 0.5 if any(a["id"] == "temp_critical" for a in active) else 1.0
        thermal = [a for a in active if a["id"] != "sensor"]
        if fired and "thermal" not in self.inc:
            learned = next((a for a in fired if a.get("cause")), None)
            if learned: cause, conf, comp = learned["cause"], 0.9, False
            else: cause, conf, comp = self._attribute(f)
            acts = [a["action"]["type"] + (f"={a['action']['value']}" if a["action"]["type"] == "derate" else "")
                    for a in active]
            ev = {k: round(v, 3) for k, v in f.items() if k in ("temp", "flow_ratio", "power_frac", "heat_resid", "temp_slope")}
            if cause == "pump_fault": ev["dtc"] = "P0A93"       # inverter/battery cooling system performance
            self._open("thermal", cause, conf, ev, acts, comp)
        if "thermal" in self.inc:
            inc = self.inc["thermal"]
            inc["actions"] = sorted(set(inc["actions"]) | {a["action"]["type"] + (f"={a['action']['value']}" if a["action"]["type"] == "derate" else "") for a in active})
            self._maybe_escalate(inc, "tick")
            lim = self.eng.rb["limits"]["warn"]
            stable = self.tick_n - inc["opened"] >= 20 and temp < lim - 3 and r.slope <= 0.002
            if not thermal or stable: self._close("thermal", "cleared")   # cleared, or mitigated and holding
        if "sensor" in self.inc:
            inc = self.inc["sensor"]; self._maybe_escalate(inc, "tick")
            if self.tick_n - inc["opened"] >= 10 and not thermal: self._close("sensor", "cleared")
        # efficiency
        k = s["Battery.kmPerKwh"]
        if self.kpk_base is None and self.tick_n > 30: self.kpk_base = self.roll["kpk"].mean
        self._mark("kpk_drop", self.kpk_base is not None and k < 0.85 * self.kpk_base)
        if "kpk_drop" in self.onset and self.tick_n - self.onset["kpk_drop"] >= 20 and "eff" not in self.inc:
            self._open("eff", "efficiency_degradation", 0.8, {"kpk": k, "base": round(self.kpk_base, 3)},
                       ["advise_eco"], needs_consent=True)
        if "eff" in self.inc and "kpk_drop" not in self.onset: self._close("eff", "cleared")
        # security: IDS, calibration integrity, grid pattern
        if frames is not None:
            flags, conf = self.ids.window(frames, own_speed=s["Vehicle.Speed"])
            if conf and "ids" not in self.inc:
                self.ctl.isolated.add("body_can")
                self._open("ids", "can_attack:" + ",".join(sorted(conf)), 0.9,
                           {"flags": sorted(flags), "novelty": round(self.ids.novelty, 2)},
                           ["isolate_can"], security=True)
            elif "ids" in self.inc and not flags:
                self.inc["ids"]["quiet"] = self.inc["ids"].get("quiet", 0) + 1
                if self.inc["ids"]["quiet"] >= 10: self._close("ids", "cleared")
            elif flags: 
                if "ids" in self.inc: self.inc["ids"]["quiet"] = 0
        if cal is not None and self.golden is not None:
            if chash(cal) != self.golden_hash and "cal" not in self.inc:
                self.cal_ok = False; cal.clear(); cal.update(self.golden)      # restore golden calibration
                self._open("cal", "calibration_tamper", 0.99, {"restored": True}, ["restore_calibration"], security=True)
            elif "cal" in self.inc and chash(cal) == self.golden_hash:
                self.cal_ok = True; self._close("cal", "cleared")
        if external.get("grid_outage") and f["soc"] < 0.5 and "grid" not in self.inc:
            self._open("grid", "grid_outage", 0.8, {"soc": f["soc"]}, ["notify_driver"], fleet_pattern=True)
        if "grid" in self.inc and not external.get("grid_outage"): self._close("grid", "cleared")
        self._diag(s, external.get("diag") or {})
        # telemetry (decimated) and ring buffer
        self.ring.append({"t": self.tick_n, **{k: v for k, v in sig.items()}})
        if self.tick_n % self.tel_every == 0:
            self.up.send({"kind": "telemetry", "vehicle_id": self.vid, "ts": self.t, "sim": self.sim,
                          "signals": sig, "edge": {"cap": round(self.ctl.power_cap, 2), "rb": self.eng.version,
                                                    "ignored": sorted(self.ctl.ignored)}})
        return {"power_cap": self.ctl.power_cap, "speed_cap": min(self.ctl.limp, self.ctl.edge_limp, *self.ctl.dtc_limp.values())}

    def _diag(self, s, diag):
        """Deterministic DTC / intrusion rules with dwell + clear-hold. Reduce-only actions."""
        env = {**DEFAULTS, **{k: v for k, v in diag.items() if isinstance(v, (int, float, bool))}, "speed": s["Vehicle.Speed"]}
        for d in DTCS:
            key, st = "dtc:" + d["dtc"], self.dtc_state[d["dtc"]]
            hit = bool(safe_eval(d["when"], env))
            if key not in self.inc:
                st["on"] = st["on"] + 1 if hit else 0
                if st["on"] >= DWELL:
                    ev = {"dtc": d["dtc"], **{k: env[k] for k in env if env[k] != DEFAULTS[k] and k != "speed"}}
                    flags = {k: True for k in ("security", "service_required") if d.get(k)}
                    for a in d["actions"]:
                        if a.startswith("derate="): self.ctl.dtc_caps[key] = float(a.split("=")[1])
                        elif a == "limp": self.ctl.dtc_limp[key] = 0.5
                        elif a.startswith(("isolate_", "stop_")): self.ctl.isolated.add(a)
                    self._open(key, d["cause"], 0.95, ev, d["actions"], **flags)
            else:
                st["off"] = st["off"] + 1 if not hit else 0
                self._maybe_escalate(self.inc[key], "tick")
                if st["off"] >= CLEAR_HOLD:
                    self.ctl.dtc_caps.pop(key, None); self.ctl.dtc_limp.pop(key, None)
                    for a in d["actions"]: self.ctl.isolated.discard(a)
                    self._close(key, "cleared"); st["on"] = 0

    def counters(self):
        tot = self.n["resolved"] + self.n["escalated"]
        return {"edge_resolved": self.n["resolved"], "escalated": self.n["escalated"],
                "resolved_ratio": self.n["resolved"] / tot if tot else None,
                "bytes_baseline": self.n["baseline_bytes"], "bytes_sent": self.up.sent_bytes,
                "bytes_saved": self.n["baseline_bytes"] - self.up.sent_bytes}
