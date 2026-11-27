"""Simulated EV: speed/power demand, stiff thermal loop (sub-stepped), faults.
Thermal: C dT/dt = k_gen*P^2 - (k_nat + k_flow*flow_frac)*(T - T_amb)  [kW, kJ/K]"""
import random

PMAX, C, KGEN, KNAT, KFLOW, NOMFLOW, TAMB = 80.0, 25.0, 0.0005, 0.05, 0.25, 12.0, 25.0
SUB = 1.0   # integrate in <=1 s sub-steps (spec: <=5 model-seconds)


class Vehicle:
    def __init__(self, vid, seed=0, sim=True, lat=12.97, lon=77.59):
        self.id, self.sim, self.r = vid, sim, random.Random(seed)
        self.T, self.soc, self.speed, self.t = 30.0, 0.8, 60.0, 0
        self.lat, self.lon = lat, lon
        self.pump_duty, self.flow_fault = 0.7, 1.0     # flow_fault 1=healthy, 0=dead
        self.temp_sensor = None                        # None | ("stuck", v) | ("offset", d)
        self.hvac_kw, self.tyre_drag = 0.5, 1.0
        self.cal = {"torque_limit": 1.0, "regen": 0.6, "fan_curve": 0.5}
        self.demand = 0.6                              # fraction of PMAX
        self.power_cap, self.speed_cap = 1.0, 1.0      # set by edge actions (reduce-only)
        self.last = {}
        self.kgen_mult, self.extra_heat_kw = 1.0, 0.0                       # hidden heat source (unknown-cause fault)

    @property
    def flow(self): return NOMFLOW * self.pump_duty * self.flow_fault * (1 if self.pump_duty > 0.05 else 0)

    def step(self, dt=1.0):
        frac = min(self.demand, self.power_cap)
        P = PMAX * frac
        tgt = 100 * frac * self.speed_cap
        self.speed += max(-3 * dt, min(3 * dt, tgt - self.speed))   # ramp, no instant jumps
        rem = dt
        while rem > 0:                                  # sub-steps keep the stiff loop stable
            h = min(SUB, rem); rem -= h
            q_in = KGEN * self.kgen_mult * P * P + self.extra_heat_kw
            q_out = (KNAT + KFLOW * self.flow / NOMFLOW) * (self.T - TAMB)
            self.T += h * (q_in - q_out) / C
        eff = 6.5 / (self.tyre_drag * (1 + self.hvac_kw / 6) )   # km/kWh
        self.kpk = eff * (1 + self.r.gauss(0, 0.01))
        self.soc = max(0, self.soc - (P + self.hvac_kw) * dt / 3600 / 60)
        self.t += dt
        return self.sample()

    def sample(self):
        T = self.T + self.r.gauss(0, 0.05)
        if self.temp_sensor:
            k, v = self.temp_sensor
            T = v if k == "stuck" else T + v
        P = PMAX * min(self.demand, self.power_cap)
        self.last = {
            "Vehicle.Speed": round(self.speed, 2), "Battery.Temp": round(T, 2),
            "Coolant.Flow": round(self.flow + self.r.gauss(0, 0.05), 3),
            "Motor.Current": round(P * 1000 / 400, 2), "Battery.SoC": round(self.soc, 4),
            "Battery.kmPerKwh": round(self.kpk, 3), "Pump.Duty": self.pump_duty, "Power.kW": round(P, 2)}
        return self.last
