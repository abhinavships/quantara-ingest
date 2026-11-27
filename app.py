"""Condense input connector entrypoint: runs the fleet at 1 Hz and publishes to
<prefix>.raw.telemetry / .raw.edge / .raw.feeds; consumes signed commands + injection requests."""
import time

from argonaut_core import config, crypto
from argonaut_core.bus import get_bus
from sim.fleet import Fleet
from sim.feeds import weather

N = int(config.env("FLEET_SIZE", "100"))


def main():
    bus = get_bus()
    pub = config.env("CLOUD_PUBKEY")
    priv = None
    if not pub:                              # dev only: ephemeral keypair, private key never logged
        priv, pub = crypto.gen_keypair()
        print("DEV MODE: ephemeral signing key; set CLOUD_PUBKEY for real runs")
    fleet = Fleet(N, bus, pub, priv)
    T, grp = config.topic, config.group("ingest")
    inbox = [T("commands.out"), T("control.inject")]
    wx, last_feed = weather(), -999
    print(f"ingest running: {N} vehicles, prefix={config.prefix()}", flush=True)
    while True:
        t0 = time.time()
        for topic, _, m in bus.poll(grp, inbox, timeout=0.01):
            if topic == T("control.inject"): fleet.inject(m["scenario"], m.get("vehicles"))
            else: bus.publish(T("raw.edge"), fleet.deliver(m), key=m.get("vehicle_id"))
        for m in fleet.step():
            bus.publish(T("raw.telemetry") if m["kind"] == "telemetry" else T("raw.edge"), m, key=m["vehicle_id"])
        if fleet.t - last_feed >= 30:
            last_feed = fleet.t
            bus.publish(T("raw.feeds"), {"kind": "feeds", "weather": wx, "grid": fleet.grid.snapshot(fleet.t),
                                         "counters": fleet.counters(), "ts": time.time()})
        time.sleep(max(0, 1.0 - (time.time() - t0)))


if __name__ == "__main__":
    main()
