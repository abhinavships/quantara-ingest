# argonaut-ingest (Input connector: simulator + edge agent)

Part 1 of 4 repos (ingest, stream, services, ops) for the Configure 2026 hackathon. **Everything is simulated.** No real vehicle is ever controlled; with `SANDBOX=1` the edge refuses any vehicle not flagged simulated.

## What it does
- `sim/`: ~100 synthetic EVs (thermal loop, CAN bus, calibration), routes from OSRM/OSM, weather from Open-Meteo, simulated grid and stations, fault injection for all four events (breakdown, grid outage, degradation, cyber).
- `edge/`: the vehicle agent, edge-first. Stats layer, JSON rulebook with a whitelisted evaluator and guarded updates, CAN IDS (rules + PCA autoencoder), reduce-only local actions, signed-command OTA client, store-and-forward uplink, explicit escalation policy with freeze frames. The edge sends compact summaries for what it resolves and escalates the rest; counters report edge-resolved vs escalated and bytes saved.
- `app.py`: the Condense input-connector entrypoint (1 Hz loop).

## Topics (prefix = `TOPIC_PREFIX`)
Publishes `<p>.raw.telemetry`, `<p>.raw.edge` (summary, escalation, security, command_result), `<p>.raw.feeds`. Consumes `<p>.commands.out`, `<p>.control.inject`.

## Env (names only)
`TOPIC_PREFIX`, `KAFKA_BOOTSTRAP`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD`, `CLOUD_PUBKEY` (base64 Ed25519 public key of the cloud), `FLEET_SIZE` (default 100), `SANDBOX` (set 1). Put them in a gitignored `.env`.

## Run / reproduce
```
python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest
pytest -q            # no infrastructure needed
python app.py        # with KAFKA_* set: publishes to Kafka; without: dev mode, in-memory bus
```
Condense: Build from this repo (Dockerfile), Publish a version, Deploy as an input connector.

## Data sources and licences
OpenStreetMap routing via the OSRM demo server (ODbL), Open-Meteo (CC BY 4.0). Everything else is generated.

## AI-use disclosure
Written with Claude Code (Claude Sonnet 5.5): the simulator, edge agent, tests and docs. Verified by the unit tests in `tests/` and, once deployed, the running pipeline. See `decisions.md`.

MIT licence.
