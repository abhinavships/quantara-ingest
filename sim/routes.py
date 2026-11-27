"""Routes: OSRM public demo server (OSM data, ODbL) with a deterministic offline fallback.
Cached to routes.json so we make a handful of polite requests, not one per vehicle."""
import json
import math
import os
import random

import requests

CITY = (12.9716, 77.5946)     # Bengaluru
CACHE = os.path.join(os.path.dirname(__file__), "routes.json")


def _fallback(r, n=60):
    la, lo = CITY[0] + r.uniform(-.08, .08), CITY[1] + r.uniform(-.08, .08)
    th, pts = r.uniform(0, 6.28), []
    for i in range(n):
        th += r.uniform(-.2, .2); la += .0012 * math.cos(th); lo += .0012 * math.sin(th); pts.append((la, lo))
    return pts


def build_routes(n=8, seed=7, online=True):
    if os.path.exists(CACHE):
        return [[tuple(p) for p in r] for r in json.load(open(CACHE))]
    r, routes = random.Random(seed), []
    for _ in range(n):
        a = (CITY[0] + r.uniform(-.1, .1), CITY[1] + r.uniform(-.1, .1))
        b = (CITY[0] + r.uniform(-.1, .1), CITY[1] + r.uniform(-.1, .1))
        pts = None
        if online:
            try:
                u = f"https://router.project-osrm.org/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}?overview=full&geometries=geojson"
                g = requests.get(u, timeout=3, headers={"User-Agent": "vehicle-sim/0.1"}).json()["routes"][0]["geometry"]["coordinates"]
                pts = [(y, x) for x, y in g][::3]
            except Exception:
                pts = None
        routes.append(pts or _fallback(r))
    json.dump(routes, open(CACHE, "w"))
    return routes
