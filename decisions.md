# Decisions (ingest repo)
1. **Clean-room build.** Rule 8 forbids a prebuilt backend. A pre-window prototype exists in the parent folder; none of it was read for or copied into these repos. Everything here was written inside the window.
2. **Python 3.12 via Dockerfile** (`python:3.12-slim`). Not confirmed that the Condense builder auto-detects 3.12; a Dockerfile makes the runtime explicit. TODO: confirm in the portal at first Build.
3. **Shared package `argonaut-core`** is installed from a git tag (`@v0.1.0`) so all repos share one config/bus/crypto/schema version.
4. **Bus abstraction with in-memory twin.** `get_bus()` returns Kafka when `KAFKA_BOOTSTRAP` is set, else an in-memory bus, so all unit tests run with no infra. Kafka producer is idempotent; publish retries with back-off; consumers rely on librdkafka reconnects.
5. **Topic names** are `<TOPIC_PREFIX>.<name>`, consumer groups `<TOPIC_PREFIX>.cg-<name>`; `/` is rejected.
6. **Evaluator is an AST whitelist** (names, numbers, bool, comparisons, + - * /). No calls/attributes/subscripts/strings/comprehensions. Division by zero returns 0.
7. **Rulebook guard**: limits may only go down (never above 45/50/58 C); mandatory rules must be byte-identical (when/clear/action/dwell/hold); non-mandatory rules may only use reduce-only actions; derate floor 0.4; version must increase. Updates keep a snapshot for rollback.
8. **Sensor faults** are detected by abrupt jump (>4 K/s) or flatline, not by model residual, because a hidden heat source also produces residual and must not be mistaken for a sensor fault. On a bad sensor the edge runs on a physics estimate and does not cut power.
9. **Escalation is a pure function** (`edge/policy.py`) separate from detection, so it is unit-tested alone. N = 120 ticks (the thermal loop has a time constant of minutes), K = 3/hour, confidence >= 0.7, competing-cause margin 0.15.
10. **A mitigated incident counts as cleared** once temp is below warn-3 and not rising for 20 ticks while the action holds, otherwise a persistent root cause with a working derate would always escalate as "unresolved".
11. **Thermal mass is compressed** (C = 25 kJ/K) so faults play out in minutes of sim time. Documented as a sim scale choice, not a pack model.
12. **IDS threshold** = 3x the worst clean-window PCA error; rule detectors are strict on deterministic clean traffic. Zero false positives is tested on 20 x 400 clean windows. Two consecutive flagged windows needed to confirm.
13. **Rate**: 100 vehicles, telemetry every 5 s each (20 msg/s). Edge decisions stream as they happen. Raw 1 Hz equivalent is counted as `bytes_baseline` to report bytes saved.
14. **Uplink buffer** drops oldest telemetry first; escalations/security are kept preferentially.
15. **OSRM fallback**: routes are cached to `sim/routes.json`; when OSRM is unreachable a deterministic random-walk route is used and the source is stated in the README.
16. **Python 3.12 confirmed** in the Condense IDE (3.12.14) and build; Dockerfile still pins it.
17. **Topics are created explicitly** at startup (`quantara_core.topics.ensure_topics`, one registry = the data contract). Do not rely on broker auto-create. Partitions/retention per topic; replication 2.
18. **Observability**: stdout logging, `PYTHONUNBUFFERED=1`, delivery-failure logging, a 30 s heartbeat with ok/failed counters and edge-resolved vs escalated.
