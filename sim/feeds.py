"""External feeds: Open-Meteo weather (CC BY 4.0) + simulated grid/stations."""
import random

import requests

STATIONS = [{"id": f"ST{i}", "lat": 12.90 + 0.02 * (i % 4) + 0.01 * (i // 4), "lon": 77.52 + 0.025 * (i // 2),
             "ports": 6, "online": True} for i in range(8)]


def weather(lat=12.97, lon=77.59):
    try:
        j = requests.get("https://api.open-meteo.com/v1/forecast", timeout=3, params={
            "latitude": lat, "longitude": lon, "current": "temperature_2m,wind_speed_10m"}).json()["current"]
        return {"ambient_c": j["temperature_2m"], "wind_kmh": j["wind_speed_10m"], "source": "open-meteo"}
    except Exception:
        return {"ambient_c": 28.0, "wind_kmh": 8.0, "source": "fallback"}


class Grid:
    def __init__(self, seed=3): self.r, self.stations, self.outage = random.Random(seed), [dict(s) for s in STATIONS], False

    def set_outage(self, on, frac=0.75):
        self.outage = on
        for i, s in enumerate(self.stations): s["online"] = not (on and i < int(len(self.stations) * frac))

    def snapshot(self, t):
        return {"outage": self.outage, "load": round(0.5 + 0.1 * self.r.random(), 2), "stations": self.stations, "ts": t}
