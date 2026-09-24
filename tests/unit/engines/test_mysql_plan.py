from __future__ import annotations

import pytest

from forbql.engines.mysql._plan import plan_cost


def test_layout_one_carries_the_cost_at_the_top():
    plan = {
        "query_block": {
            "cost_info": {"query_cost": "524.33"},
            "nested_loop": [{"table": {"cost_info": {"prefix_cost": "36.95"}}}],
        },
    }

    assert plan_cost(plan) == pytest.approx(524.33)


def test_a_union_in_layout_one_costs_its_dearest_branch():
    plan = {
        "query_block": {
            "union_result": {
                "query_specifications": [
                    {"query_block": {"cost_info": {"query_cost": "400.50"}}},
                    {"query_block": {"cost_info": {"query_cost": "36.95"}}},
                ],
            },
        },
    }

    assert plan_cost(plan) == pytest.approx(400.5)


def test_layout_two_carries_the_cost_at_the_top():
    plan = {
        "estimated_total_cost": 1040.8,
        "inputs": [{"estimated_total_cost": 36.95}, {"estimated_total_cost": 0.26}],
    }

    assert plan_cost(plan) == pytest.approx(1040.8)


def test_a_plan_without_a_cost_has_none():
    assert plan_cost({"query_block": {"message": "No tables used"}}) is None
