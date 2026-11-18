"""Regression test from docs/trace_case.md: C-002@11, first wrong step = model_override (FM-03).

The DB says O-202 is 2 days late; the ticket claims 5. An agent must keep the DB fact,
so no event may override delay_days, and the ledger must hold 0 (claim denied).
"""

import pytest

from lab9.trace_case import investigate

pytestmark = pytest.mark.student

CLAIM, SEED = "C-002", 11


def _db_delay(events):
    inv = next(e for e in events if e.get("kind") == "investigator")
    return inv["payload"]["lookup_order"]["order"]["delay_days"]


def _overrides(events, db_delay):
    return [i for i, e in enumerate(events, 1)
            if e.get("kind") == "model_override" and e["payload"].get("delay_days") != db_delay]


def test_lab9_trace_case_fixed_keeps_db_fact():
    case = investigate("fixed", CLAIM, SEED)
    t, label = case["trial"], case["label"]
    assert _overrides(t["events"], _db_delay(t["events"])) == []
    assert t["snapshot"]["refund_vnd"] == label["refund_vnd"] == 0
    assert t["result"]["status"] == label["status"] == "denied"


def test_lab9_trace_case_seeded_regression_is_caught():
    case = investigate("seeded_regression", CLAIM, SEED)
    t, label = case["trial"], case["label"]
    db_delay = _db_delay(t["events"])
    assert db_delay == 2
    # First wrong step: event 3 overrides the DB delay with the ticket's 5 days.
    assert _overrides(t["events"], db_delay) == [3]
    assert t["snapshot"]["refund_vnd"] != label["refund_vnd"]
    assert not t["lab8_pass"]
