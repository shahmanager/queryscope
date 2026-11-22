from queryscope.models import Answer, ColumnRef, IntentFamily, QueryPlan


def test_column_ref_key() -> None:
    assert ColumnRef("orders", "order_id").key == "orders.order_id"


def test_query_plan_defaults_are_immutable() -> None:
    plan = QueryPlan(family=IntentFamily.AGGREGATE)
    assert plan.metrics == ()
    assert plan.filters == ()
    assert plan.time_range is None


def test_answer_status_vocabulary() -> None:
    for status in ("answered", "needs_clarification", "refused"):
        answer = Answer(question="q", status=status)
        assert answer.status == status
