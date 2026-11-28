"""Glue: one vehicle + CAN bus + edge agent, stepped together. Used by tests and the fleet."""
from quantara_core import crypto
from edge.agent import Agent
from edge.ids import PcaAE, feats
from sim.can import CanBus
from sim.vehicle import Vehicle

_MODEL = {}


def ids_model():
    if "m" not in _MODEL:
        b = CanBus(1); _MODEL["m"] = PcaAE().fit([feats(b.window(t)) for t in range(300)])
    return _MODEL["m"]


class Rig:
    def __init__(self, vid="V1", seed=1, pub=None, priv=None, rulebook=None, policy=None, sim=True):
        self.priv, self.pub = (priv, pub) if priv else crypto.gen_keypair()
        self.out = []
        self.v, self.bus = Vehicle(vid, seed, sim), CanBus(seed)
        self.agent = Agent(vid, sim, self.out.append, ids_model(), self.pub, policy, rulebook,
                           golden_cal=dict(self.v.cal))
        self.external, self.maxT, self.diag = {}, 0.0, {}

    def run(self, n, demand=None, hook=None):
        if demand is not None: self.v.demand = demand
        for i in range(n):
            if hook: hook(self, i)
            s = self.v.step()
            fr = self.bus.window(self.v.t, self.v.speed, s["Motor.Current"], self.v.T)
            o = self.agent.tick(s, fr, {**self.external, "diag": self.diag}, cal=self.v.cal)
            self.v.power_cap, self.v.speed_cap = o["power_cap"], o["speed_cap"]
            self.maxT = max(self.maxT, self.v.T)
        return self

    def kinds(self, k): return [m for m in self.out if m["kind"] == k]
