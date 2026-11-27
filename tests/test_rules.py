import copy
import pytest
from edge.evaluator import safe_eval, UnsafeExpression
from edge.rulebook import Engine, DEFAULT, validate_update


@pytest.mark.parametrize("src", [
    "__import__('os').system('x')", "().__class__", "[x for x in [1]]", "(lambda: 1)()",
    "temp.real", "'a'", "open('f')", "temp[0]", "f(1)", "{1:2}", "temp if 1 else 2", "_x > 1"])
def test_evaluator_rejects_code(src):
    with pytest.raises(UnsafeExpression):
        safe_eval(src, {"temp": 1, "f": 1, "_x": 1})


def test_evaluator_ok():
    assert safe_eval("a > 1 and not (b < 2) or a * 2 == 6", {"a": 3, "b": 5})
    assert safe_eval("1 < a < 4", {"a": 3})
    assert safe_eval("a / b", {"a": 1, "b": 0}) == 0.0


def upd(f):
    n = copy.deepcopy(DEFAULT); n["version"] = 2; f(n); return n


def test_update_cannot_raise_limits_or_remove_mandatory():
    assert validate_update(DEFAULT, upd(lambda n: n["limits"].update(critical=70)))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["limits"].update(warn=46)))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["rules"].pop(2)))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["rules"][1]["action"].update(value=1.0)))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["rules"][1].update(when="temp > 99")))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["rules"].append(
        {"id": "x", "when": "temp > 1", "clear": "temp < 1", "action": {"type": "derate", "value": 0.1}})))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["rules"].append(
        {"id": "x", "when": "temp > 1", "clear": "temp < 1", "action": {"type": "boost", "value": 2}})))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["rules"].append(
        {"id": "x", "when": "__import__('os')", "clear": "temp < 1", "action": {"type": "alert", "value": 1}})))[0] is False
    assert validate_update(DEFAULT, upd(lambda n: n["limits"].update(critical=55)))[0] is True
    stale = copy.deepcopy(DEFAULT)
    assert validate_update(DEFAULT, stale)[0] is False   # version not increased


def test_hysteresis_no_chatter():
    e = Engine(); fired = cleared = 0
    # temp oscillates +-1 C around the derate limit (50): must fire once, never chatter
    for i in range(200):
        t = 50 + (1 if i % 2 else -1) + 0.5
        f, c, _ = e.step({"temp": t, "flow_ratio": 1.0}); fired += len(f); cleared += len(c)
    assert fired <= 3 and cleared == 0   # warn+derate (+critical never) fire once; none clear


def test_dwell_and_clear_hold():
    e = Engine()
    assert e.step({"temp": 51, "flow_ratio": 1})[0] == []           # dwell 2 not met
    f, _, _ = e.step({"temp": 51, "flow_ratio": 1})
    assert any(r["id"] == "temp_derate" for r in f)
    for _ in range(7):                                                # clear_hold 8 not yet met
        assert all(r["id"] != "temp_derate" for r in e.step({"temp": 40, "flow_ratio": 1})[1])
    assert any(r["id"] == "temp_derate" for r in e.step({"temp": 40, "flow_ratio": 1})[1])


def test_rollback():
    e = Engine(); n = upd(lambda n: n["limits"].update(critical=55))
    assert e.apply_update(n)[0] and e.version == 2
    e.rollback(); assert e.version == 1
