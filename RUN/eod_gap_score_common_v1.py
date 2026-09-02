# -*- coding: utf-8 -*-
"""Pure EOD_GAP raw-score calculation shared by live and order-zero boards."""


def calculate_raw_score(rank0, universe_size, turnover, value20, opt_after,
                        intraday, theme_rank, current_close, close_prev, close5):
    """Return the unchanged production raw score and its components.

    All inputs are already captured market observations.  This module deliberately
    imports no broker, order, TR, or environment-dependent code.
    """
    intraday = intraday or None
    opt_after = opt_after or None
    vr = (turnover / value20) if (value20 and value20 > 0) else 0
    p_val_abs = (1.0 - rank0 / max(universe_size, 1)) * 20
    p_val_20 = (10 if vr >= 3 else 7 if vr >= 2 else 4 if vr >= 1.5
                else max(0, (vr - 1) / 0.5 * 4))
    if opt_after and opt_after["n"] >= 2:
        p_aft = (min(opt_after["aft_ratio"] / 0.4, 1.0) * 5
                 + min(opt_after["late_ratio"] / 0.15, 1.0) * 3
                 + (2 if opt_after["sustained"] else 0))
    elif intraday:
        p_aft = (min(intraday["aft_val_eok"] / 50.0, 1.0) * 5
                 + min(intraday["pm_ratio"] / 0.4, 1.0) * 5)
    else:
        p_aft = 0
    p_aft = min(p_aft, 10)
    p_value = p_val_abs + p_val_20 + p_aft

    close_pos = intraday["close_pos"] if intraday else 0.5
    p_close = ((8 if (intraday and intraday["vwap_over"]) else 0)
               + close_pos * 7
               + (5 if intraday and intraday["late_drop"] >= -1 else 0)
               + max(0, 1 - (intraday["upper_wick"] if intraday else 0.3) / 0.5) * 5)
    p_boom = 0
    if intraday:
        p_boom = min((5 if intraday["big13"] else 0)
                     + (7 if intraday["big1430"] else 0)
                     + (5 if intraday["big_spike"] else 0)
                     + (5 if intraday["follow"] else 0)
                     + (3 if intraday["vwap_over"] else 0), 20)
    p_theme = 6 if theme_rank == 1 else 4 if theme_rank == 2 else 0
    p_rs = (3 if (close5 and current_close > close5) else 0) + 2
    score = round(p_value + p_close + p_boom + p_theme + p_rs, 1)
    day_ret = (current_close / close_prev - 1) if close_prev else 0
    return {
        "score": score,
        "value_score": p_value,
        "close_score": p_close,
        "boom_score": p_boom,
        "theme_score": p_theme,
        "relative_score": p_rs,
        "volume_ratio": vr,
        "day_return": day_ret,
    }
