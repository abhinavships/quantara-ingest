"""Condense input connector entrypoint: runs the fleet at 1 Hz and publishes to
<prefix>raw.telemetry / raw.edge / raw.feeds; consumes signed commands + injection requests."""
import logging
import sys
import time

from quantara_core import config, crypto, topics
from quantara_core.bus import get_bus
from sim.feeds import weather
from sim.fleet import Fleet

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingest")
N = int(config.env("FLEET_SIZE", "100"))


def main():
    log.info("starting prefix=%s fleet=%d sandbox=%s", config.prefix(), N, config.env("SANDBOX"))
    bus = get_bus()
    if config.env("KAFKA_BOOTSTRAP"):
        try:
            res = topics.ensure_topics()
            log.info("topics: %s", res)
        except Exception as e:                       # keep running; publisher retries
            log.error("ensure_topics failed: %s", e)
    pub = config.env("CLOUD_PUBKEY")
    priv = None
    if not pub:                                      # dev only: ephemeral keypair, private key never logged
        priv, pub = crypto.gen_keypair()
        log.warning("DEV MODE: ephemeral signing key; set CLOUD_PUBKEY for real runs")
    fleet = Fleet(N, bus, pub, priv)
    T, grp = config.topic, config.group("ingest")
    inbox = [T("commands.out"), T("control.inject")]
    wx, last_feed, last_beat = weather(), -999, 0
    log.info("running: %d vehicles", len(fleet.rigs))
    while True:
        t0 = time.time()
        try:
            for topic, _, m in bus.poll(grp, inbox, timeout=0.01):
                if topic == T("control.inject"): fleet.inject(m["scenario"], m.get("vehicles"), params=m.get("params"))
                else: bus.publish(T("raw.edge"), fleet.deliver(m), key=m.get("vehicle_id"))
            for m in fleet.step():
                bus.publish(T("raw.telemetry") if m["kind"] == "telemetry" else T("raw.edge"), m, key=m["vehicle_id"])
            if fleet.t - last_feed >= 30:
                last_feed = fleet.t
                bus.publish(T("raw.feeds"), {"kind": "feeds", "weather": wx, "grid": fleet.grid.snapshot(fleet.t),
                                             "counters": fleet.counters(), "ts": time.time()})
            if fleet.t - last_beat >= 30:
                last_beat = fleet.t
                log.info("t=%ds ok=%s failed=%s edge=%s", fleet.t, getattr(bus, "ok", "-"),
                         getattr(bus, "failed", "-"), fleet.counters())
        except Exception:
            log.exception("loop error (continuing)")
        time.sleep(max(0, 1.0 - (time.time() - t0)))


if __name__ == "__main__":
    main()
