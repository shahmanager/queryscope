import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "business"))

from roi import RoiInputs, calculate


def test_roi_hand_computed() -> None:
    result = calculate(RoiInputs(
        queries_per_day=100,
        working_days_per_year=200,
        analyst_minutes_saved_per_query=6,
        blended_analyst_rate_usd=100,
        build_effort_hours=100,
        build_rate_usd=100,
        adoption_fraction=1.0,
    ))
    # 100*200 = 20,000 queries; 6 min each = 2,000 h; at $100 = $200,000
    assert result.annual_queries == 20_000
    assert result.analyst_hours_saved == 2_000.0
    assert result.annual_labor_savings_usd == 200_000.0
    assert result.net_annual_benefit_usd == 200_000.0
    assert result.one_time_build_cost_usd == 10_000.0


def test_llm_baseline_and_payback() -> None:
    result = calculate(RoiInputs(queries_per_day=100, working_days_per_year=200, adoption_fraction=1.0))
    # 20,000 * 1,200 tokens / 1000 * $0.01 = $240
    assert result.llm_baseline_annual_cost_usd == 240.0
    assert result.payback_working_days > 0
