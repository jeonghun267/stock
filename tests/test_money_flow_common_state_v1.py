from RUN.money_flow_common_state_v1 import (
    FLOW_CONTINUING,
    FLOW_NONE,
    FLOW_TURNING,
    build_common_flow_tags,
)


def _micro(ts, buy, sell, price):
    return {
        "ts": ts,
        "buy_money_cum": buy,
        "sell_money_cum": sell,
        "buy_vol_cum": 500,
        "sell_vol_cum": 500,
        "cur": price,
    }


def test_tags_do_not_filter_reorder_or_change_rank():
    rows = [
        {"code": "000001", "rank": 1, "name": "가"},
        {"code": "000002", "rank": 2, "name": "나"},
    ]
    tagged, _, counts = build_common_flow_tags(
        rows,
        {
            "000001": _micro("2026-09-01T09:00:00", 1_000_000, 2_000_000, 1_000),
            "000002": _micro("2026-09-01T09:00:00", 1_000_000, 2_000_000, 2_000),
        },
        {},
    )
    assert [(row["code"], row["rank"]) for row in tagged] == [("000001", 1), ("000002", 2)]
    assert all(row["common_flow_state"] == FLOW_NONE for row in tagged)
    assert counts[FLOW_NONE] == 2


def test_turning_then_continuing_after_three_positive_samples():
    rows = [{"code": "000001", "rank": 1}]
    tagged, state, _ = build_common_flow_tags(
        rows, {"000001": _micro("2026-09-01T09:00:00", 1_000_000, 2_000_000, 1_000)}, {}
    )
    assert tagged[0]["common_flow_state"] == FLOW_NONE

    samples = [
        ("2026-09-01T09:00:20", 2_000_000, 2_100_000, 1_001),
        ("2026-09-01T09:00:40", 3_000_000, 2_200_000, 1_002),
        ("2026-09-01T09:01:00", 4_000_000, 2_300_000, 1_003),
    ]
    seen = []
    for ts, buy, sell, price in samples:
        tagged, state, _ = build_common_flow_tags(
            rows, {"000001": _micro(ts, buy, sell, price)}, state
        )
        seen.append(tagged[0]["common_flow_state"])

    assert seen[0] == FLOW_TURNING
    assert seen[-1] == FLOW_CONTINUING
