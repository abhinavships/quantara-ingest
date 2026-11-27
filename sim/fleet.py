"""Fleet: ~100 simulated vehicles, each with its own edge agent. Real-time ticking,
fault injection for the four events, signed-command delivery."""
from sim.feeds import Grid
from sim.routes import build_routes
from sim.runner import Rig

SCENARIOS = ("breakdown", "grid_outage", "degradation", "cyber_flood", "cyber_fuzz", "cyber_spoof",
             "cyber_replay", "cal_tamper", "telemetry_mismatch", "pump_recover", "clear", "link_down", "link_up")


class Fleet:
    def __init__(self, n, bus, pub, priv=None, seed=1, routes=None):
        self.bus = bus
        self.routes = routes or build_routes()
        self.grid, self.rigs, self.pos, self.mismatch = Grid(), {}, {}, set()
        self.out = []
        for i in range(n):
            vid = f"V{i:03d}"
            rig = Rig(vid, seed + i, pub=pub, priv=priv)
            rig.agent.up.pub = self.out.append
            rig.v.demand = 0.55 + 0.05 * (i % 4)
            self.rigs[vid] = rig; self.pos[vid] = (i % len(self.routes), (i * 7) % 50)
        self.t = 0

    def inject(self, scenario, vids=None, **kw):
        vids = vids or list(self.rigs)[:1]
        if scenario == "grid_outage":
            self.grid.set_outage(True)
            for r in self.rigs.values(): r.v.soc = min(r.v.soc, 0.35)
            return
        if scenario == "clear": self.grid.set_outage(False)
        for vid in vids:
            r = self.rigs[vid]
            if scenario == "breakdown": r.v.demand = 1.0; r.v.flow_fault = kw.get("flow_fault", 0.0)
            elif scenario == "pump_recover": r.v.flow_fault = 1.0
            elif scenario == "degradation": r.v.tyre_drag = 1.6
            elif scenario.startswith("cyber_"): r.bus.attack = scenario[6:]
            elif scenario == "cal_tamper": r.v.cal["torque_limit"] = 3.0
            elif scenario == "telemetry_mismatch": self.mismatch.add(vid)
            elif scenario == "link_down": r.agent.up.set_link(False)
            elif scenario == "link_up": r.agent.up.set_link(True)
            elif scenario == "clear":
                r.bus.attack = None; r.v.flow_fault = 1.0; r.v.tyre_drag = 1.0; r.v.demand = 0.6
                self.mismatch.discard(vid)

    def deliver(self, cmd):
        r = self.rigs.get(cmd.get("vehicle_id"))
        if not r:
            return {"kind": "command_result", "ok": False, "why": "unknown vehicle", "ts": self.t}
        ok, why = r.agent.ota.handle(cmd)
        return {"kind": "command_result", "vehicle_id": cmd["vehicle_id"], "ok": ok, "why": why,
                "counter": cmd.get("counter"), "cmd_kind": cmd.get("kind"), "ts": self.t}

    def step(self):
        self.t += 1
        self.out.clear()
        for vid, r in self.rigs.items():
            r.external = {"grid_outage": self.grid.outage}
            r.run(1)
            ri, k = self.pos[vid]; route = self.routes[ri]
            self.pos[vid] = (ri, k + 1)
            r.v.lat, r.v.lon = route[(k // 4) % len(route)]
        msgs = list(self.out)
        for m in msgs:
            if m["kind"] == "telemetry":
                r = self.rigs[m["vehicle_id"]]
                m["lat"], m["lon"] = round(r.v.lat, 5), round(r.v.lon, 5)
                if m["vehicle_id"] in self.mismatch: m["signals"]["Battery.Temp"] -= 18   # lies vs physics
        return msgs

    def counters(self):
        agg = {"edge_resolved": 0, "escalated": 0, "bytes_baseline": 0, "bytes_sent": 0, "bytes_saved": 0}
        for r in self.rigs.values():
            c = r.agent.counters()
            for k in agg: agg[k] += c[k]
        tot = agg["edge_resolved"] + agg["escalated"]
        agg["resolved_ratio"] = agg["edge_resolved"] / tot if tot else None
        return agg
