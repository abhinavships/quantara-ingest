"""Edge OTA client: verifies signature, vehicle id, expiry, monotonic counter,
guard ranges and consent/OEM proofs. Every rejection is returned with a reason."""
import time

from quantara_core import crypto

NEEDS_CONSENT = {"behavioural", "software", "raise_power", "security_patch", "rulebook_update"}
NEEDS_OEM = {"security_patch", "software"}
GUARDS = {"derate": ("limit", 0.4, 1.0), "limp": ("speed_frac", 0.2, 1.0),
          "raise_power": ("limit", 0.4, 1.0)}


class OtaClient:
    def __init__(self, vehicle_id, pub_b64, controller, engine, clock=time.time):
        self.vid, self.pub, self.ctl, self.eng, self.clock = vehicle_id, pub_b64, controller, engine, clock
        self.counter, self.log = 0, []

    def _rej(self, why): self.log.append(("rejected", why)); return False, why

    def handle(self, cmd: dict):
        if not crypto.verify(cmd, self.pub): return self._rej("bad signature")
        if cmd.get("vehicle_id") != self.vid: return self._rej("wrong vehicle")
        if cmd.get("expires", 0) < self.clock(): return self._rej("expired")
        if cmd.get("counter", 0) <= self.counter: return self._rej("replayed counter")
        kind, p = cmd.get("kind"), cmd.get("params", {})
        if kind in NEEDS_CONSENT:
            c = cmd.get("consent") or {}
            if not (c.get("decision") == "approved" and c.get("counter") == cmd["counter"]
                    and c.get("vehicle_id") == self.vid):
                return self._rej("consent missing")
        if kind in NEEDS_OEM:
            o = cmd.get("oem_approval") or {}
            if not (o.get("approved") and o.get("counter") == cmd["counter"]): return self._rej("oem approval missing")
        if kind in GUARDS:
            f, lo, hi = GUARDS[kind]
            if not (isinstance(p.get(f), (int, float)) and lo <= p[f] <= hi): return self._rej("out of guard range")
        if kind == "derate": self.ctl.cloud_cap = p["limit"]
        elif kind == "limp": self.ctl.limp = p["speed_frac"]
        elif kind == "raise_power":
            if p["limit"] > self.ctl.cloud_cap and self.ctl.hot: return self._rej("unsafe to raise")
            self.ctl.cloud_cap = p["limit"]
        elif kind == "rulebook_update":
            ok, why = self.eng.apply_update(p["rulebook"])
            if not ok: return self._rej(why)
        elif kind == "rollback": self.eng.rollback()
        elif kind in ("behavioural", "software", "security_patch"): self.ctl.applied.append((kind, p))
        else: return self._rej("unknown kind")
        self.counter = cmd["counter"]
        self.log.append(("applied", kind))
        return True, "ok"
