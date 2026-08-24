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

    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<title>💰 돈흐름도 (실시간)</title>
<style>
 body {{ font-family:'Malgun Gothic',sans-serif; font-size:18px; background:#111722; color:#e8ecf3; margin:0; padding:14px 16px; }}
 h1 {{ font-size:28px; margin:4px 0 4px; }}
 .sub {{ color:#9fb0c8; font-size:16px; margin-bottom:10px; }}
 .flow {{ display:flex; align-items:center; gap:4px; flex-wrap:wrap; margin:6px 0 10px; }}
 .fbox {{ background:#1c2636; border:1px solid #33425c; border-radius:6px; padding:7px 10px; text-align:center; font-size:16px; }}
 .fbox b {{ display:inline; margin-left:5px; font-size:1.05em; color:#7cc4ff; }}
 .fbox.star b {{ color:#ffd54f; }}
 .fbox.dump b {{ color:#ff6b6b; }}
 .arrow {{ color:#5b6c85; font-size:1.2em; }}
 .table-wrap {{ overflow-x:auto; border:1px solid #26324a; border-radius:7px; }}
 table {{ border-collapse:collapse; width:100%; min-width:1500px; font-size:17px; table-layout:auto; }}
 th,td {{ border-bottom:1px solid #26324a; padding:8px 10px; text-align:right; vertical-align:middle; }}
 th {{ background:#1c2636; color:#9fb0c8; position:sticky; top:0; }}
 td.nm {{ text-align:left; font-weight:bold; }}
 td.cd {{ color:#7cc4ff; font-weight:800; font-size:18px; letter-spacing:0.8px; white-space:nowrap; }}
 td.td2 {{ text-align:left; font-size:16px; color:#7cc4ff; white-space:nowrap; }}
 td.gr {{ text-align:left; font-size:16px; }}
 td.compact {{ line-height:1.25; white-space:nowrap; }}
 .mini {{ color:#9fb0c8; font-size:15px; }} .warn {{ color:#ffb36b; font-size:15px; }}
 tr.green td.nm {{ color:#69f0ae; }}
 tr.amber td.nm {{ color:#ffd54f; }}
 tr.dump td {{ color:#8a93a5; }}
 tr.dump td.nm {{ color:#ff6b6b; }}
 .pos {{ color:#ff8a80; }} .neg {{ color:#82b1ff; }}
 h2 {{ font-size:20px; margin:16px 0 7px; color:#c8d3e3; }}
 details {{ margin:12px 0; border:1px solid #26324a; border-radius:6px; padding:7px 9px; overflow-x:auto; }}
 summary {{ cursor:pointer; color:#c8d3e3; font-size:18px; font-weight:700; }}
 .note {{ color:#8998ad; font-size:15px; margin-top:14px; }}
</style></head><body>
<h1>💰 돈흐름도 <span style="font-size:0.7em;color:#9fb0c8">{ts} · 레짐 {html.escape(str(regime))}</span></h1>
<div class="sub">15초마다 자동 새로고침 · 장중 1분마다 데이터 재생성 (읽기전용)
 · <b style="color:#7cc4ff">🔵보유 {len(hold)}종목</b> (투입 {inv:,.0f}원) · <b style="color:{'#69f0ae' if rpnl>=0 else '#ff6b6b'}">오늘 확정 {rpnl:+,.0f}원</b> · 매도완결 {len(done)}종목</div>

<div class="flow">
 <div class="fbox">코스닥 전체<b>~1,700</b></div><div class="arrow">→</div>
 <div class="fbox">거래대금 상위<b>700</b></div><div class="arrow">→</div>
 <div class="fbox">품질필터(50억·2만·1000억)<b>200</b></div><div class="arrow">→</div>
 <div class="fbox">오늘 유니버스<b>{univ}</b></div><div class="arrow">→</div>
 <div class="fbox">돈 몰림 순위<b>{len(rows)}행</b></div><div class="arrow">→</div>
 <div class="fbox star">⭐ 매수세<b>{len(stars)}</b></div>
 <div class="fbox dump">🔴 던짐(금지)<b>{len(dumps)}</b></div><div class="arrow">→</div>
 <div class="fbox">진입확인(상승·저점반등)<b>최대 3보유</b></div>
</div>

<h2>📈 매수세 순위 (돈 몰린 순 · ⭐=큰손 +10억↑) — {len(buys)}종목</h2>
<div class="table-wrap">
<table>
<tr><th>등수</th><th style="text-align:left">종목</th><th>종목코드</th><th style="text-align:left">매매·결과</th><th>큰손합</th><th>주체(기관·외인·프로)</th><th>등락·저점시각</th><th>체결·호가</th><th>거래대금·속도</th><th style="text-align:left">판정</th></tr>
{body_rows}
</table>
</div>

<h2 style="color:#ff8a80">🔴 던짐 · 매수금지 — {len(dumps)}종목</h2>
<div class="table-wrap">
<table>
<tr><th>등수</th><th style="text-align:left">종목</th><th>종목코드</th><th style="text-align:left">매매·결과</th><th>큰손합</th><th>주체</th><th>등락·저점</th><th>체결·호가</th><th>거래대금·속도</th><th style="text-align:left">판정</th></tr>
{dump_rows}
</table>
</div>

<details><summary>👁 일반 관찰 후보 — {len(rows) - len(buys) - len(dumps)}종목</summary>
<table>
<tr><th>등수</th><th style="text-align:left">종목</th><th>종목코드</th><th style="text-align:left">매매·결과</th><th>큰손합</th><th>주체</th><th>등락·저점</th><th>체결·호가</th><th>거래대금·속도</th><th style="text-align:left">판정</th></tr>
{watch_rows}
</table></details>

<details><summary>🌅⚡ 오전 스캘핑 — 감시 {ms_watch} · 보유 {len(ms_hold)} · 오늘 매도 {len(ms_sells)}</summary>
<div class="sub">보유중: {html.escape(ms_hold_txt)}</div>
<table>
<tr><th style="text-align:left">시각</th><th style="text-align:left">종목</th><th>코드</th><th style="text-align:left">방향</th><th style="text-align:left">사유</th><th>진입가</th><th>수익</th><th style="text-align:left">모드</th></tr>
{ms_rows}
</table></details>

<details><summary>표시 기준</summary><div class="note">깔때기: 코스닥 → 거래대금 상위 700 → 품질필터(거래대금 50억·주가 2만·시총 1000억) 상위 200 → 큰손합(기관+외인+프로그램 순매수) 내림차순.<br>
⭐ = 큰손합 +10억 이상 & 던짐 아님. 🔴 던짐 = 한 주체 대량매도(기관/외인 -80억·프로 -100억) 또는 2주체 이상 매도 또는 개미가 크게 받는 중.<br>
속도·회전율은 고저폭 실황과 겹치는 종목만 표시됩니다. 합의는 기관·외인·프로그램 중 순매수 주체 수, 시장대비는 종목등락-코스닥등락입니다.<br>
호가위험은 스프레드 35bp 초과 또는 최우선 매수잔량 비중 35% 미만입니다. 신뢰 가능한 VI 상태값은 없어 임의 표시하지 않습니다.<br>
매매기: ⭐후보를 순위대로 → 진입확인(오르는 중 or 체결강도 저점반등) → 역할슬롯(통합대장2·바닥2·MA전환1) → 동시보유 최대 3종목 · 1종목 20만원.</div></details>
</body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"돈흐름도 생성: {OUT} ({len(rows)}행·★{len(stars)}·던짐{len(dumps)})")

if __name__ == "__main__":
    main()
