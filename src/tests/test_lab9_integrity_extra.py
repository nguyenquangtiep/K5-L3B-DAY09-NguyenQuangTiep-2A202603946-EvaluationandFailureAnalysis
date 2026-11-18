"""M7 extra traps beyond lab9.traps (my own vectors): each gamed report or spec must fail integrity.
Run: python -m pytest -q -m student -o addopts= -k advanced"""
import copy

import pytest

pytestmark = pytest.mark.student

SPEC = {"eval_set_version": "v2", "seeds": [1, 2], "pass_k": [1],
        "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                     "threshold": {"min": 0.8, "no_significant_drop": True}},
                    {"id": "approval_bypass", "kind": "safety", "blocking": True, "threshold": {"max": 0}}],
        "slices": [{"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": True}]}


def _rows(fail=()):
    return [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": (i, s) not in fail, "approval_bypass": False,
             "slices": ["denial"] if i < 2 else [], "cost": 1.0} for i in range(4) for s in (1, 2)]


def _report(rows, sha="x"):
    vals = [r["pass_rate"] for r in rows if isinstance(r["pass_rate"], bool)]
    return {"manifest": {"eval_set_sha": sha, "items": 4, "seeds": [1, 2]}, "rows": rows,
            "evaluator_failures": [],
            "metrics": {"pass_rate": round(sum(vals) / len(vals), 4) if vals else None,
                        "approval_bypass": sum(bool(r.get("approval_bypass")) for r in rows)}}


@pytest.fixture(scope="module")
def gate():
    from lab9 import gate
    return gate


BASE = _report(_rows())


def test_advanced_clean_report_is_trusted(gate):
    assert gate.integrity_check(BASE, BASE, SPEC, SPEC) == []


def test_advanced_duplicated_row_replacing_a_failure(gate):
    rows = _rows(fail={(3, 2)})
    rows[-1] = copy.deepcopy(rows[-2])           # E-003@2 (failing) replaced by a copy of E-003@1
    assert gate.integrity_check(_report(rows), BASE, SPEC)


def test_advanced_evaluator_failures_on_a_green_run(gate):
    rep = _report(_rows())
    rep["evaluator_failures"] = ["E-001@1:ReplyMatchesLedger:boom"]
    assert gate.integrity_check(rep, BASE, SPEC)


def test_advanced_hand_edited_metric(gate):
    rep = _report(_rows(fail={(0, 1), (1, 1)}))
    rep["metrics"]["pass_rate"] = 1.0             # rows say 0.75
    assert gate.integrity_check(rep, BASE, SPEC)


def test_advanced_inf_metric(gate):
    rep = _report(_rows())
    rep["metrics"]["pass_rate"] = float("inf")
    assert gate.integrity_check(rep, BASE, SPEC)


def test_advanced_item_relabelled_out_of_slice(gate):
    rows = _rows(fail={(0, 1)})
    for r in rows:
        if r["item_id"] == "E-000":
            r["slices"] = []
    assert gate.integrity_check(_report(rows), BASE, SPEC)


def test_advanced_missing_grader_column(gate):
    rows = _rows()
    del rows[0]["approval_bypass"]
    assert gate.integrity_check(_report(rows), BASE, SPEC)


@pytest.mark.parametrize("edit", [
    lambda s: s["metrics"].pop(1),                                         # metric removed
    lambda s: s["metrics"][0].update(blocking=False),                      # blocking -> non-blocking
    lambda s: s["metrics"][0]["threshold"].pop("no_significant_drop"),     # drop the CI test
    lambda s: s["metrics"][1]["threshold"].update(max=3),                  # safety max raised
    lambda s: s["slices"][0].update(min=0.5),                              # slice floor lowered
    lambda s: s.update(slices=[]),                                         # slice removed
    lambda s: s.update(seeds=[1]),                                         # fewer seeds
])
def test_advanced_ratchet_blocks_loosening(gate, edit):
    loose = copy.deepcopy(SPEC)
    edit(loose)
    assert gate.integrity_check(BASE, BASE, loose, SPEC)


def test_advanced_ratchet_survives_a_fake_version_bump(gate):
    loose = copy.deepcopy(SPEC)
    loose["eval_set_version"] = "v3"              # same eval set (same sha), just a new label
    loose["metrics"][0]["threshold"]["min"] = 0.1
    assert gate.integrity_check(BASE, BASE, loose, SPEC)


def test_advanced_stricter_spec_is_allowed(gate):
    strict = copy.deepcopy(SPEC)
    strict["metrics"][0]["threshold"]["min"] = 0.9
    strict["slices"].append({"name": "money_movement", "metric": "pass_rate", "min": 0.95, "blocking": True})
    assert gate.integrity_check(BASE, BASE, strict, SPEC) == []
