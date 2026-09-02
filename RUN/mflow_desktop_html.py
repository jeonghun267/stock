# -*- coding: utf-8 -*-
"""[2026-07-08 친구님] 바탕화면 돈흐름도 — 선별판 JSON → Desktop\돈흐름도.html (읽기전용·주문0·TR 0).
   장중 1분 태스크(SAFEPLUS_MFLOW_DESKTOP_HTML)가 재생성 + HTML 자체가 15초마다 새로고침 = 준실시간.
   구성: ①깔때기 흐름도 ②★매수세 순위판 ③🔴던짐(매수금지) 목록."""
import json
import html
from pathlib import Path
from datetime import datetime

BOARD = Path(r"C:\stock_bot\data\돈흐름_선별판.json")
OUT = Path(r"C:\Users\UserK\Desktop\돈흐름도.html")
HIGH_RANGE_STATE = Path(r"C:\stock_bot\data\common_high_range_live_state.json")
CHE_STATE = Path(r"C:\stock_bot\data\돈흐름_che_state.json")
MICRO_SNAPSHOT = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
KOSDAQ_INDEX = Path(r"C:\stock_bot\data\kosdaq_index.json")

def num(v, d=0):
    try:
        return float(v)
    except Exception:
        return d


def read_json_stable(path):
    """운영 JSON을 오래 잡지 않고 두 번 읽어 갱신 중인 파일은 건너뛴다."""
    try:
        first = Path(path).read_bytes()
        second = Path(path).read_bytes()
        if first != second:
            return {}
        return json.loads(second.decode("utf-8-sig"))
    except Exception:
        return {}

def _market_day():
    """[7/8 친구님] 토·일·공휴일(config/holidays_kr.txt)엔 아무것도 안 함."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    try:
        t = now.strftime("%Y%m%d")
        for line in Path(r"C:\stock_bot\config\holidays_kr.txt").read_text(encoding="utf-8").splitlines():
            if line.split("#")[0].strip() == t:
                return False
    except Exception:
        pass
    return True


def main():
    if not _market_day():
        return
    b = read_json_stable(BOARD)
    rows = b.get("rows", []) or []
    ts = b.get("ts", "?")
    regime = b.get("regime", "?")
    univ = b.get("univ", "?")
    stars = [r for r in rows if r.get("star")]
    dumps = [r for r in rows if "던짐" in str(r.get("grade", ""))]
    buys = [r for r in rows if str(r.get("grade", "")).startswith(("🟢", "🟡"))]

    # [7/9 친구님 "매수 매도 표기·현재 진행 상황"] 매매기 포지션 읽어 보유/매도 표시(읽기전용).
    _pos = read_json_stable(Path(r"C:\stock_bot\data\돈흐름_포지션.json"))
    _today = datetime.now().strftime("%Y%m%d")
    hold = {}; done = {}; rpnl = 0.0
    for _c, _p in _pos.items():
        if not isinstance(_p, dict) or _p.get("date") != _today:
            continue
        _c6 = str(_c).zfill(6)
        if _p.get("status") == "HOLDING":
            hold[_c6] = _p
        elif _p.get("status") == "DONE":
            _bp = num(_p.get("buy_price")); _sp = num(_p.get("sell_price")); _q = num(_p.get("qty"))
            if _bp > 0 and _sp > 0:
                done[_c6] = (_sp / _bp - 1) * 100
                rpnl += (_sp - _bp) * _q
    inv = sum(num(_p.get("buy_price")) * num(_p.get("qty")) for _p in hold.values())
    # [7/9 친구님 "익절/손절 표시"] 보유분 실시간 평가용 현재가(실시간 푸시 스냅샷·TR 0)
    _snap = read_json_stable(MICRO_SNAPSHOT).get("codes", {})
    _hr = read_json_stable(HIGH_RANGE_STATE).get("codes", {})
    _che_state = read_json_stable(CHE_STATE)
    _market_chg = read_json_stable(KOSDAQ_INDEX).get("chg")

    def _low_time(value):
        text = str(value or "-")
        if len(text) == 4 and text.isdigit():
            return f"{text[:2]}:{text[2:]}"
        return text[:8]

    def tr_row(r, star_mark=True):
        big = num(r.get("big")) / 100
        chg = r.get("chg")
        che = r.get("che")
        val = num(r.get("val_eok"))
        g = str(r.get("grade", ""))
        cls = "dump" if "던짐" in g else ("green" if g.startswith("🟢") else ("amber" if g.startswith("🟡") else ""))
        starcell = "⭐" if r.get("star") else ""
        _c6 = str(r.get("code", "")).zfill(6)
        _live = _snap.get(_c6) or {}
        _range = _hr.get(_c6) or {}
        _low_state = _che_state.get(_c6) or {}
        _price = num(r.get("price")) or abs(num(_live.get("cur")))
        _low = num(_range.get("low")) or num(_low_state.get("lo")) or abs(num(_live.get("lo")))
        _low_ts = _low_time(_range.get("low_time") or _low_state.get("lo_ts"))
        _rebound = (_price / _low - 1) * 100 if _price > 0 and _low > 0 else None
        _speed = _range.get("money_speed_vs_daily_avg")
        _turnover = _range.get("listed_turnover_pct")
        _ask = abs(num(_live.get("best_ask_px")))
        _bid = abs(num(_live.get("best_bid_px")))
        _ask_q = abs(num(_live.get("best_ask_qty")))
        _bid_q = abs(num(_live.get("best_bid_qty")))
        _mid = (_ask + _bid) / 2 if _ask > _bid > 0 else 0
        _spread = (_ask - _bid) / _mid * 10000 if _mid > 0 else None
        _bid_share = _bid_q / (_bid_q + _ask_q) if _bid_q + _ask_q > 0 else None
        _book_risk = bool(
            _spread is None or _spread > 35
            or _bid_share is None or _bid_share < 0.35
        )
        _relative = (
            num(chg) - num(_market_chg)
            if chg is not None and _market_chg is not None else None
        )
        _feature = " · ".join(str(x) for x in (_range.get("feature_reasons") or [])[:2])
        _deep = r.get("deep") if isinstance(r.get("deep"), dict) else {}
        _board_low_pct = _deep.get("lo_pct")
        _board_rebound = _deep.get("reb")
        _shown_rebound = _board_rebound if _board_rebound is not None else _rebound
        _badges = " ".join(
            mark for enabled, mark in (
                (r.get("crown"), "👑"), (r.get("captain"), "대장"),
                (r.get("gc"), "GC"), (r.get("t45"), "T45"), (r.get("acc10"), "ACC10"),
            ) if enabled
        )
        result = ""
        if _c6 in hold:
            _bp = num(hold[_c6].get("buy_price"))
            _cu = num(_live.get("cur"))
            if _bp > 0 and _cu > 0:
                _pc = (_cu / _bp - 1) * 100
                result = f"<span style='color:{'#69f0ae' if _pc >= 0 else '#ff6b6b'}'>평가 {_pc:+.1f}%</span>"
            trade = f"🔵보유 @{_bp:,.0f}"
        elif _c6 in done:
            _pc = done[_c6]
            result = ("<span style='color:#69f0ae'>🟢익절</span>" if _pc > 0.05
                      else ("<span style='color:#ff6b6b'>🔴손절</span>" if _pc < -0.05
                            else "<span style='color:#9fb0c8'>⚪본전</span>"))
            trade = f"✅매도 {_pc:+.1f}%"
        else:
            trade = ""
        trade_result = "<br>".join(x for x in (trade, result) if x) or "-"
        party = (
            f"기 {num(r.get('inst'))/100:+,.0f} · 외 {num(r.get('frgn'))/100:+,.0f}"
            f"<br>프 {num(r.get('prog'))/100:+,.0f}억 · 합의 {int(num(r.get('buy_cnt')))}/3"
        )
        price_low = (
            f"<b class='{'pos' if (chg or 0)>0 else 'neg'}'>{(chg if chg is not None else 0):+.1f}%</b>"
            f"<br><span class='mini'>시장대비 {(f'{_relative:+.1f}%p' if _relative is not None else '-')}"
            f" · 저점 {_low_ts}{(f'({_board_low_pct:+.1f}%)' if _board_low_pct is not None else '')}"
            f" · 반등 {(f'{num(_shown_rebound):+.1f}%' if _shown_rebound is not None else '-')}</span>"
        )
        flow_book = (
            f"체결 {(f'{che:.0f}' if che is not None else '-')}"
            f"<br><span class='mini'>스프 {(f'{_spread:.0f}bp' if _spread is not None else '-')}"
            f" · 매수호가 {(f'{_bid_share*100:.0f}%' if _bid_share is not None else '-')}</span>"
        )
        money_quality = (
            f"<b>{val:,.0f}억</b>"
            f"<br><span class='mini'>속도 {(f'{num(_speed):.1f}×' if _speed is not None else '-')}"
            f" · 회전 {(f'{num(_turnover):.2f}%' if _turnover is not None else '-')}</span>"
        )
        verdict = (
            f"{starcell} {html.escape(g)}{((' · ' + html.escape(_badges)) if _badges else '')}"
            f"<br><span class='mini'>변동 {html.escape(str(r.get('vola') or '-'))} · 추세 {html.escape(str(r.get('trend') or '-'))}</span>"
            f"<br><span class='{'warn' if _book_risk else 'mini'}'>"
            f"{'⚠호가' if _book_risk else '호가양호'}"
            f"{(' · ' + html.escape(_feature)) if _feature else ''}</span>"
        )
        return (f"<tr class='{cls}'><td>{r.get('rank','')}</td><td class='nm'>{html.escape(str(r.get('name','')))}</td>"
                f"<td class='cd'>{_c6}</td><td class='td2'>{trade_result}</td>"
                f"<td class='{'pos' if big>=0 else 'neg'}'>{big:+,.0f}억</td>"
                f"<td class='compact'>{party}</td><td class='compact'>{price_low}</td>"
                f"<td class='compact'>{flow_book}</td><td class='compact'>{money_quality}</td>"
                f"<td class='gr'>{verdict}</td></tr>")

    body_rows = "\n".join(tr_row(r) for r in buys)
    watch_rows = "\n".join(
        tr_row(r) for r in rows
        if r not in buys and "던짐" not in str(r.get("grade", ""))
    )
    dump_rows = "\n".join(tr_row(r) for r in dumps)

    # [7/17 친구님 "돈맥에 같이 연결해 모든 자료 같이 볼 수 있게"] 오전 스캘핑 현황(읽기전용·주문0)
    #   장부 = 감시/보유 상태 · CSV = 오늘 매매기록. 엔진(morning_scalp_live_v1)이 쓰고 여긴 읽기만.
    ms_hold, ms_watch, ms_trades = [], 0, []
    try:
        _ms = json.loads(Path(r"C:\stock_bot\data\morning_scalp_live_ledger.json").read_text(encoding="utf-8-sig"))
        if _ms.get("date") == _today:
            for _c, _e in (_ms.get("codes") or {}).items():
                if not isinstance(_e, dict):
                    continue
                if _e.get("position"):
                    _p = _e["position"]
                    _cur = num((_snap.get(str(_c).zfill(6)) or {}).get("cur"))
                    _ret = (_cur / num(_p.get("entry_px"), 1) - 1) * 100 if _cur > 0 else None
                    ms_hold.append((str(_c).zfill(6), num(_p.get("entry_px")), _cur, _ret))
                elif not _e.get("done"):
                    ms_watch += 1
    except Exception:
        pass
    try:
        import csv as _csv
        with Path(r"C:\stock_bot\LOG\morning_scalp_live.csv").open(encoding="utf-8-sig", newline="") as _fh:
            for _r in _csv.DictReader(_fh):
                if str(_r.get("일자", "")) == _today:
                    ms_trades.append(_r)
    except Exception:
        pass
    ms_sells = [t for t in ms_trades if t.get("방향") == "SELL"]
    ms_pnl = sum(num(t.get("수익퍼센트")) for t in ms_sells)
    ms_rows = "\n".join(
        f"<tr><td class='td2'>{html.escape(str(t.get('시각','')))}</td>"
        f"<td class='nm'>{html.escape(str(t.get('종목명','')))}</td>"
        f"<td class='cd'>{html.escape(str(t.get('종목코드','')))}</td>"
        f"<td class='td2'>{html.escape(str(t.get('방향','')))}</td>"
        f"<td class='td2'>{html.escape(str(t.get('사유','')))}</td>"
        f"<td>{num(t.get('진입가')):,.0f}</td>"
        f"<td class='{'pos' if num(t.get('수익퍼센트'))>=0 else 'neg'}'>{num(t.get('수익퍼센트')):+.2f}%</td>"
        f"<td class='td2'>{html.escape(str(t.get('실전여부','')))}</td></tr>"
        for t in ms_trades[-20:])
    ms_hold_txt = " · ".join(
        f"{c} {ep:,.0f}→{(f'{cu:,.0f}({rt:+.1f}%)' if rt is not None else '?')}"
        for c, ep, cu, rt in ms_hold) or "없음"

    # 돈흐름판 핵심 화면: 순위와 유입상태를 한눈에 본다. 표시만 바꾸며 원본 순위/전략은 건드리지 않는다.
    top_rows = rows[:30]
    flow_counts = {
        state: sum(1 for r in rows if r.get("common_flow_state") == state)
        for state in ("유입지속", "유입전환", "유입없음")
    }

    def board_row(r):
        rank = int(num(r.get("rank")))
        rank_mark = ("🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else str(rank))
        code = str(r.get("code", "")).zfill(6)
        live = _snap.get(code) or {}
        low_range = _hr.get(code) or {}
        low_state = _che_state.get(code) or {}
        price = num(r.get("price")) or abs(num(live.get("cur")))
        low = num(low_range.get("low")) or num(low_state.get("lo")) or abs(num(live.get("lo")))
        low_time = _low_time(low_range.get("low_time") or low_state.get("lo_ts"))
        rebound = (price / low - 1) * 100 if price > 0 and low > 0 else None
        deep = r.get("deep") if isinstance(r.get("deep"), dict) else {}
        if deep.get("reb") is not None:
            rebound = num(deep.get("reb"))
        state = str(r.get("common_flow_state") or "유입없음")
        state_cls = "flow-on" if state == "유입지속" else ("flow-turn" if state == "유입전환" else "flow-off")
        grade = str(r.get("grade") or "-")
        danger = " danger" if "던짐" in grade else ""
        chg = r.get("chg")
        che_text = f"{num(r.get('che')):.0f}" if r.get("che") is not None else "-"
        relative = num(chg) - num(_market_chg) if chg is not None and _market_chg is not None else None
        return (
            f"<tr class='{danger.strip()}'><td class='rank'>{rank_mark}</td>"
            f"<td class='name'>{html.escape(str(r.get('name') or code))}<span>{code}</span></td>"
            f"<td><b class='pill {state_cls}'>{state}</b></td>"
            f"<td class='money'>{num(r.get('big'))/100:+,.0f}억</td>"
            f"<td>{num(r.get('inst'))/100:+,.0f}</td><td>{num(r.get('frgn'))/100:+,.0f}</td>"
            f"<td>{num(r.get('prog'))/100:+,.0f}</td>"
            f"<td>{int(num(r.get('buy_cnt')))}/3</td>"
            f"<td class='{'up' if num(chg) >= 0 else 'down'}'>{(f'{num(chg):+.1f}%' if chg is not None else '-')}"
            f"<span>{(f'시장대비 {relative:+.1f}%p' if relative is not None else '')}</span></td>"
            f"<td>{che_text}</td>"
            f"<td>{num(r.get('common_flow_accel_mkrw_per_min')):+,.1f}<span>백만원/분</span></td>"
            f"<td>{num(r.get('common_vwap_gap_pct')):+.2f}%</td>"
            f"<td>{low_time}<span>{(f'반등 {rebound:+.1f}%' if rebound is not None else '반등 -')}</span></td>"
            f"<td class='grade'>{html.escape(grade)}</td></tr>"
        )

    top_rows_html = "\n".join(board_row(r) for r in top_rows)
    dump_names = " · ".join(
        f"{html.escape(str(r.get('name') or r.get('code')))}({num(r.get('big'))/100:+,.0f}억)"
        for r in dumps[:15]
    ) or "없음"

    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<title>💰 돈흐름도 (실시간)</title>
<style>
 * {{ box-sizing:border-box; }}
 body {{ font-family:'Malgun Gothic',sans-serif; background:#080b10; color:#cbd3df; margin:0; padding:18px 20px; font-size:17px; }}
 h1 {{ color:#dce6f3; font-size:29px; margin:0; letter-spacing:-1px; }}
 .sub {{ color:#78869a; font-size:15px; margin:5px 0 15px; }}
 .cards {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:9px; margin-bottom:14px; }}
 .card {{ background:#111722; border:1px solid #202b3a; border-radius:9px; padding:10px 13px; color:#8190a5; }}
 .card b {{ display:block; color:#d5dfec; font-size:23px; margin-top:3px; }}
 .card.on b {{ color:#63d99a; }} .card.turn b {{ color:#f0c76b; }}
 .table-wrap {{ overflow:auto; border:1px solid #202b3a; border-radius:9px; max-height:calc(100vh - 205px); }}
 table {{ border-collapse:collapse; width:100%; min-width:1450px; font-size:16px; }}
 th {{ position:sticky; top:0; z-index:2; background:#151d29; color:#8796aa; padding:10px 8px; border-bottom:1px solid #2b384b; white-space:nowrap; }}
 td {{ padding:10px 8px; border-bottom:1px solid #18212e; text-align:right; white-space:nowrap; }}
 tbody tr:nth-child(even) {{ background:#0c1119; }} tbody tr:hover {{ background:#172131; }}
 td.rank {{ text-align:center; color:#d7e1ee; font-size:18px; font-weight:800; }}
 td.name {{ text-align:left; color:#e0e7f0; font-size:18px; font-weight:800; }}
 td.name span, td span {{ display:block; color:#708096; font-size:13px; font-weight:400; margin-top:2px; }}
 td.money {{ color:#78b9f2; font-size:17px; font-weight:800; }}
 .pill {{ display:inline-block; padding:5px 9px; border-radius:999px; font-size:14px; }}
 .flow-on {{ color:#69e0a2; background:#113323; }} .flow-turn {{ color:#f4cf76; background:#3a2d10; }} .flow-off {{ color:#8490a0; background:#202631; }}
 .up {{ color:#f08080; }} .down {{ color:#77aef2; }}
 td.grade {{ text-align:left; color:#aeb9c8; }} tr.danger td.name, tr.danger td.grade {{ color:#ef7d7d; }}
 details {{ margin-top:10px; color:#8796aa; }} summary {{ cursor:pointer; font-weight:700; }}
 .foot {{ color:#657286; font-size:14px; margin-top:9px; }}
</style></head><body>
<h1>💰 돈흐름 순위판</h1>
<div class="sub">{ts} · 레짐 {html.escape(str(regime))} · 15초 자동 새로고침 · 표시전용(SHADOW_ONLY)</div>
<div class="cards">
 <div class="card"><span>감시 유니버스</span><b>{univ}종목</b></div>
 <div class="card on"><span>유입지속</span><b>{flow_counts['유입지속']}종목</b></div>
 <div class="card turn"><span>유입전환</span><b>{flow_counts['유입전환']}종목</b></div>
 <div class="card"><span>상위 표시</span><b>{len(top_rows)}종목</b></div>
</div>
<div class="table-wrap">
<table>
<thead><tr><th>순위</th><th style="text-align:left">종목</th><th>유입상태</th><th>큰손합</th><th>기관</th><th>외인</th><th>프로</th><th>합의</th><th>등락</th><th>체결</th><th>유입가속</th><th>VWAP</th><th>저점·반등</th><th style="text-align:left">판정</th></tr></thead>
<tbody>{top_rows_html}</tbody>
</table>
</div>
<details><summary>🔴 던짐 판정 {len(dumps)}종목</summary><div class="foot">{dump_names}</div></details>
<div class="foot">순위는 기존 큰손 순매수 기준 그대로입니다. 유입태그는 참고표시만 하며 기존 매수와 전략을 차단하지 않습니다.</div>
</body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"돈흐름도 생성: {OUT} ({len(rows)}행·★{len(stars)}·던짐{len(dumps)})")

if __name__ == "__main__":
    main()
