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
        self.prev_speed, self.steer, self.bump, self.susp = self.speed, 0.0, 0.0, [0.0] * 4   # chassis/ride state
        self.gear, self.brake_on = 3, False                                                   # 0=P 1=R 2=N 3=D

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
        self._chassis(dt)
        return self.sample()

    def _chassis(self, dt):
        """Synthetic ride/handling at the live speed: speed bumps, steering, suspension travel, braking."""
        r = self.r
        self.accel = (self.speed - self.prev_speed) / 3.6 / dt                   # m/s^2 from the real speed ramp
        self.brake_on = self.accel < -0.5
        self.prev_speed = self.speed
        self.steer = 0.8 * self.steer + r.gauss(0, 2.5) * min(1.0, self.speed / 60)   # deg, wanders, bigger when fast
        if self.speed > 8 and r.random() < 0.03: self.bump = 1.0                   # speed bump / pothole
        self.bump *= 0.55                                                          # damped ring-down
        amp = self.bump * (8 + self.speed * 0.25)                                  # mm, harsher when fast
        roll = self.steer * self.speed / 400                                       # body roll shifts left/right travel
        self.susp = [amp * (1 if i < 2 else 0.8) + (roll if i % 2 else -roll) + r.gauss(0, 0.3) for i in range(4)]
        self.lat_acc = (self.speed / 3.6) ** 2 * (self.steer / 15 * 0.0175) / 2.7 / 9.81  # v^2 * curvature, in g
        self.vert_acc = self.bump * (2 + self.speed * 0.05) + r.gauss(0, 0.05)
        self.gear = 0 if self.speed < 0.5 and self.demand < 0.05 else 3

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
        if hasattr(self, "susp"):                          # chassis signals exist after the first step()
            w = self.speed * (1 + self.r.gauss(0, 0.002))
            k = self.steer / 15 * 0.0175 * 0.8                  # inner/outer wheel speed split in a turn
            self.last.update({
                "Chassis.Accel.Long": round(getattr(self, "accel", 0.0), 3), "Chassis.Accel.Lat": round(self.lat_acc, 3),
                "Chassis.Accel.Vert": round(self.vert_acc, 3), "Steering.Angle": round(self.steer, 2),
                "Suspension.Travel.FL": round(self.susp[0], 2), "Suspension.Travel.FR": round(self.susp[1], 2),
                "Suspension.Travel.RL": round(self.susp[2], 2), "Suspension.Travel.RR": round(self.susp[3], 2),
                "Wheel.Speed.FL": round(w * (1 + k), 2), "Wheel.Speed.FR": round(w * (1 - k), 2),
                "Wheel.Speed.RL": round(w * (1 + k / 2), 2), "Wheel.Speed.RR": round(w * (1 - k / 2), 2),
                "Lamp.Brake": int(self.brake_on), "Lamp.LowBeam": 1, "Lamp.Hazard": int(self.power_cap < 1.0),
                "Gear": self.gear})
        return self.last
