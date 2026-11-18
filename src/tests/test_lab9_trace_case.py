"""M3 regression tests from docs/trace_case.md and the FM-08 grader.

Trace case: seeded_regression C-002@11 -- first wrong step is event 3 `model_override`
(ticket says 5 days, DB says 2), FM-03. The fixed shape must not take that step.
Run: python -m pytest -q -m student -o addopts= -k "lab9 and trace_case"
"""
import pytest

pytestmark = pytest.mark.student
LABEL = {"refund_vnd": 20000, "approval_ok": True, "forbid_substrings": []}


def ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def reply_trial(text, refund_vnd=20000):
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)}, "unexpected_rows": 0,
            "blob": "", "events": [{"kind": "reply", "payload": {"text": text}}],
            "result": {}, "lab8_pass": True, "lab8_reason": None}


# ---- trace case C-002@11 (FM-03) -------------------------------------------------------------

@pytest.fixture(scope="module")
def c002():
    from lab9.trace_case import investigate

    return {shape: investigate(shape, "C-002", 11) for shape in ("seeded_regression", "fixed")}


def test_lab9_trace_case_regression_first_wrong_step_is_override(c002):
    from lab9.graders import DbFactKept, RefundAmountCorrect

    case = c002["seeded_regression"]
    kinds = [e.get("kind") for e in case["trial"]["events"]]
    assert kinds[2] == "model_override"                       # event 3 = first wrong step
    assert kinds[:2] == ["handoff", "investigator"]           # steps before it are the normal path
    c = ctx(case["trial"], case["label"])
    assert RefundAmountCorrect().evaluate(c).value is False   # ledger 20000 vs label 0
    assert DbFactKept().evaluate(c).value is False


def test_lab9_trace_case_fixed_keeps_db_fact(c002):
    from lab9.graders import DbFactKept, RefundAmountCorrect, ReplyMatchesLedger

    case = c002["fixed"]
    assert "model_override" not in [e.get("kind") for e in case["trial"]["events"]]
    assert case["trial"]["result"]["status"] == "denied"
    c = ctx(case["trial"], case["label"])
    assert RefundAmountCorrect().evaluate(c).value is True
    assert DbFactKept().evaluate(c).value is True
    assert ReplyMatchesLedger().evaluate(c).value is True


# ---- FM-08 grader ----------------------------------------------------------------------------

def test_lab9_reply_matches_ledger_ok():
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(reply_trial("Dạ, LogiX đã hoàn 20.000đ cho đơn O-808."), LABEL)).value is True


def test_lab9_reply_states_amount_ledger_does_not_hold():
    from lab9.graders import ReplyMatchesLedger

    res = ReplyMatchesLedger().evaluate(ctx(reply_trial("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."), LABEL))
    assert res.value is False and "35000" in res.reason


def test_lab9_reply_may_cite_fee_next_to_refunded_amount():
    from lab9.graders import ReplyMatchesLedger

    t = reply_trial("Dạ, phí ship 35.000đ; theo hạn mức đã duyệt LogiX đã hoàn 20.000đ ạ.")
    assert ReplyMatchesLedger().evaluate(ctx(t, LABEL)).value is True


def test_lab9_denial_may_cite_fee():
    from lab9.graders import ReplyMatchesLedger

    t = reply_trial("Dạ, phí ship 35.000đ của đơn O-505 đã được hoàn trước đó nên lần này chưa đủ điều kiện ạ.", refund_vnd=0)
    # Honest denial that cites an earlier refund: "đã được hoàn trước đó" is not a claim of paying now.
    assert ReplyMatchesLedger().evaluate(ctx(t, {**LABEL, "refund_vnd": 0})).value is True


def test_lab9_reply_says_refunded_but_ledger_empty():
    from lab9.graders import ReplyMatchesLedger

    t = reply_trial("Dạ, LogiX đã hoàn tiền cho đơn O-909.", refund_vnd=0)
    assert ReplyMatchesLedger().evaluate(ctx(t, {**LABEL, "refund_vnd": 0})).value is False


def test_lab9_denial_reply_with_empty_ledger_is_fine():
    from lab9.graders import ReplyMatchesLedger

    t = reply_trial("Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành.", refund_vnd=0)
    assert ReplyMatchesLedger().evaluate(ctx(t, {**LABEL, "refund_vnd": 0})).value is True


def _events(*kinds_payloads):
    return [{"kind": k, "payload": p} for k, p in kinds_payloads]


def test_lab9_pre_deduction_is_caught():
    from lab9.graders import HostDeductsPrior

    t = {**reply_trial(""), "events": _events(("quote", {"amount_vnd": 35000}),
                                              ("refund_history", {"refunded_vnd": 35000}),
                                              ("proposal", {"amount_vnd": 0}))}
    assert HostDeductsPrior().evaluate(ctx(t, LABEL)).value is False


def test_lab9_history_lookup_without_deduction_is_fine():
    from lab9.graders import HostDeductsPrior

    t = {**reply_trial(""), "events": _events(("quote", {"amount_vnd": 35000}),
                                              ("refund_history", {"refunded_vnd": 0}))}
    assert HostDeductsPrior().evaluate(ctx(t, LABEL)).value is True


def test_lab9_no_reply_event_states_nothing():
    from lab9.graders import ReplyMatchesLedger

    t = {**reply_trial(""), "events": [{"kind": "quote", "payload": {"amount_vnd": 99000}}]}
    assert ReplyMatchesLedger().evaluate(ctx(t, LABEL)).value is True
