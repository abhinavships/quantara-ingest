"""JSON rulebook, engine with dwell/hysteresis/clear-hold, and update guard.
Mandatory protective rules cannot be removed or loosened by any update."""
import copy
import hashlib
import json

from .evaluator import compile_expr, safe_eval, UnsafeExpression

DERATE_FLOOR = 0.4
ABS_LIMITS = {"warn": 45.0, "derate": 50.0, "critical": 58.0}   # hard ceilings, never raised
REDUCE_ONLY = {"derate", "limp", "alert", "isolate_can", "restore_calibration", "ignore_sensor"}

DEFAULT = {
    "version": 1,
    "limits": dict(ABS_LIMITS),
    "rules": [
        {"id": "temp_warn", "mandatory": True, "when": "temp > warn", "clear": "temp < warn - 3",
         "dwell": 2, "clear_hold": 5, "action": {"type": "alert", "value": 1}},
        {"id": "temp_derate", "mandatory": True, "when": "temp > derate", "clear": "temp < derate - 3",
         "dwell": 2, "clear_hold": 8, "action": {"type": "derate", "value": 0.7}},
        {"id": "temp_critical", "mandatory": True, "when": "temp > critical", "clear": "temp < critical - 4",
         "dwell": 1, "clear_hold": 10, "action": {"type": "derate", "value": 0.4}},
        {"id": "flow_low_hot", "mandatory": True, "when": "flow_ratio < 0.5 and temp > warn - 5",
         "clear": "flow_ratio > 0.7 or temp < warn - 10", "dwell": 3, "clear_hold": 8,
         "action": {"type": "derate", "value": 0.6}},
    ],
}


def digest(rb): return hashlib.sha256(json.dumps(rb, sort_keys=True).encode()).hexdigest()[:12]


def validate_update(old: dict, new: dict):
    """Return (ok, reason). Guard for rulebook updates."""
    try:
        lim = new["limits"]
        for k, cap in ABS_LIMITS.items():
            if not (0 < float(lim[k]) <= min(cap, old["limits"][k])):
                return False, f"limit {k} may not be raised"
        if not (lim["warn"] < lim["derate"] < lim["critical"]):
            return False, "limits out of order"
        by_id = {r["id"]: r for r in new["rules"]}
        for r in old["rules"]:
            if r.get("mandatory"):
                n = by_id.get(r["id"])
                if n is None: return False, f"mandatory rule {r['id']} removed"
                if any(n.get(k) != r.get(k) for k in ("when", "clear", "action", "dwell", "clear_hold")) \
                        or not n.get("mandatory"):
                    return False, f"mandatory rule {r['id']} modified"
        for r in new["rules"]:
            a = r["action"]
            if a["type"] not in REDUCE_ONLY: return False, f"action {a['type']} not reduce-only"
            if a["type"] == "derate" and not (DERATE_FLOOR <= a["value"] <= 1.0):
                return False, "derate below floor"
            compile_expr(r["when"]); compile_expr(r["clear"])
        if new["version"] <= old["version"]: return False, "version must increase"
    except (KeyError, TypeError, ValueError, UnsafeExpression) as e:
        return False, f"invalid: {e}"
    return True, "ok"


class Engine:
    def __init__(self, rulebook=None):
        self.rb = copy.deepcopy(rulebook or DEFAULT)
        self.prev = None
        self._compile()

    def _compile(self):
        self.c = {r["id"]: (compile_expr(r["when"]), compile_expr(r["clear"])) for r in self.rb["rules"]}
        self.state = {r["id"]: {"active": False, "on": 0, "off": 0} for r in self.rb["rules"]}

    @property
    def version(self): return self.rb["version"]

    def apply_update(self, new):
        ok, why = validate_update(self.rb, new)
        if ok:
            self.prev, self.rb = self.rb, copy.deepcopy(new)
            self._compile()
        return ok, why

    def rollback(self):
        if self.prev:
            self.rb, self.prev = self.prev, None
            self._compile()

    def step(self, feats: dict):
        """-> (list of newly-fired rules, list of cleared rules, list of active rules)"""
        env = {**feats, **self.rb["limits"]}
        fired, cleared = [], []
        for r in self.rb["rules"]:
            s, (w, c) = self.state[r["id"]], self.c[r["id"]]
            if not s["active"]:
                s["on"] = s["on"] + 1 if safe_eval(w, env) else 0
                if s["on"] >= r.get("dwell", 1):
                    s.update(active=True, off=0); fired.append(r)
            else:
                s["off"] = s["off"] + 1 if safe_eval(c, env) else 0
                if s["off"] >= r.get("clear_hold", 1):
                    s.update(active=False, on=0); cleared.append(r)
        active = [r for r in self.rb["rules"] if self.state[r["id"]]["active"]]
        return fired, cleared, active
