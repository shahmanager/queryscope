"""Consulting-style ROI model for adopting QueryScope.

Every input is an explicit, editable assumption. Outputs are deterministic
and suitable for a client business case — no hidden pricing claims.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RoiInputs:
    queries_per_day: int = 120
    working_days_per_year: int = 240
    analyst_minutes_saved_per_query: float = 8.0
    blended_analyst_rate_usd: float = 85.0
    build_effort_hours: float = 80.0
    build_rate_usd: float = 85.0
    annual_hosting_usd: float = 0.0
    llm_tokens_per_query: int = 1200
    llm_usd_per_1k_tokens: float = 0.01
    adoption_fraction: float = 0.7


@dataclass(frozen=True)
class RoiResult:
    annual_queries: int
    adopted_queries: int
    analyst_hours_saved: float
    annual_labor_savings_usd: float
    queryscope_annual_cost_usd: float
    net_annual_benefit_usd: float
    llm_baseline_annual_cost_usd: float
    cost_per_query_usd: float
    one_time_build_cost_usd: float
    payback_working_days: float
    annual_roi_percent: float


def calculate(inputs: RoiInputs) -> RoiResult:
    annual = inputs.queries_per_day * inputs.working_days_per_year
    adopted = int(annual * inputs.adoption_fraction)
    hours = adopted * inputs.analyst_minutes_saved_per_query / 60
    labor = hours * inputs.blended_analyst_rate_usd
    cost = inputs.annual_hosting_usd
    llm_cost = adopted * inputs.llm_tokens_per_query / 1000 * inputs.llm_usd_per_1k_tokens
    build = inputs.build_effort_hours * inputs.build_rate_usd
    daily_benefit = labor / inputs.working_days_per_year
    payback = build / daily_benefit if daily_benefit else float("inf")
    return RoiResult(
        annual_queries=annual,
        adopted_queries=adopted,
        analyst_hours_saved=round(hours, 1),
        annual_labor_savings_usd=round(labor, 2),
        queryscope_annual_cost_usd=round(cost, 2),
        net_annual_benefit_usd=round(labor - cost, 2),
        llm_baseline_annual_cost_usd=round(llm_cost, 2),
        cost_per_query_usd=0.0,
        one_time_build_cost_usd=round(build, 2),
        payback_working_days=round(payback, 1),
        annual_roi_percent=round((labor - cost - build) / build * 100, 1) if build else 0.0,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QueryScope adoption ROI model")
    for field in RoiInputs.__dataclass_fields__:
        parser.add_argument("--" + field.replace("_", "-"), type=float, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    supplied = {
        key: value for key, value in vars(args).items()
        if value is not None and key != "json"
    }
    result = calculate(RoiInputs(**supplied))
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print("QueryScope - adoption business case")
        for key, value in asdict(result).items():
            print(f"  {key:34s} {value:,}")
        print("\nAll figures depend on the assumptions passed in; see business/roi.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
