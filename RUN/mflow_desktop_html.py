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

def num(v, d=0):
    try:
        return float(v)
    except Exception:
        return d

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
    try:
        b = json.loads(BOARD.read_text(encoding="utf-8"))
    except Exception:
        b = {}
    rows = b.get("rows", []) or []
    ts = b.get("ts", "?")
    regime = b.get("regime", "?")
    univ = b.get("univ", "?")
    stars = [r for r in rows if r.get("star")]
    dumps = [r for r in rows if "던짐" in str(r.get("grade", ""))]
    buys = [r for r in rows if str(r.get("grade", "")).startswith(("🟢", "🟡"))]

    # [7/9 친구님 "매수 매도 표기·현재 진행 상황"] 매매기 포지션 읽어 보유/매도 표시(읽기전용).
    try:
        _pos = json.loads(Path(r"C:\stock_bot\data\돈흐름_포지션.json").read_text(encoding="utf-8"))
    except Exception:
        _pos = {}
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
    try:
        _snap = json.loads(Path(r"C:\stock_bot\IPC\live_micro_snapshot.json").read_text(encoding="utf-8-sig")).get("codes", {})
    except Exception:
        _snap = {}

    def tr_row(r, star_mark=True):
        big = num(r.get("big")) / 100
        chg = r.get("chg")
        che = r.get("che")
        val = num(r.get("val_eok"))
        g = str(r.get("grade", ""))
        cls = "dump" if "던짐" in g else ("green" if g.startswith("🟢") else ("amber" if g.startswith("🟡") else ""))
        starcell = "⭐" if r.get("star") else ""
        _c6 = str(r.get("code", "")).zfill(6)
        result = ""
        if _c6 in hold:
            _bp = num(hold[_c6].get("buy_price"))
            _cu = num((_snap.get(_c6) or {}).get("cur"))
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
        return (f"<tr class='{cls}'><td>{r.get('rank','')}</td><td class='nm'>{html.escape(str(r.get('name','')))}</td>"
                f"<td class='cd'>{_c6}</td><td class='td2'>{result}</td><td class='td2'>{trade}</td>"
                f"<td class='{'pos' if big>=0 else 'neg'}'>{big:+,.0f}억</td>"
                f"<td>{num(r.get('inst'))/100:+,.0f}</td><td>{num(r.get('frgn'))/100:+,.0f}</td><td>{num(r.get('prog'))/100:+,.0f}</td>"
                f"<td class='{'pos' if (chg or 0)>0 else 'neg'}'>{(chg if chg is not None else 0):+.1f}%</td>"
                f"<td>{(f'{che:.0f}' if che is not None else '-')}</td><td>{val:,.0f}억</td>"
                f"<td>{starcell}</td><td class='gr'>{g}</td></tr>")

    body_rows = "\n".join(tr_row(r) for r in rows if "던짐" not in str(r.get("grade", "")))
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
 body {{ font-family:'Malgun Gothic',sans-serif; background:#111722; color:#e8ecf3; margin:0; padding:16px; }}
 h1 {{ font-size:1.25em; margin:4px 0 2px; }}
 .sub {{ color:#9fb0c8; font-size:0.85em; margin-bottom:12px; }}
 .flow {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin:12px 0 18px; }}
 .fbox {{ background:#1c2636; border:1px solid #33425c; border-radius:8px; padding:8px 12px; text-align:center; font-size:0.85em; }}
 .fbox b {{ display:block; font-size:1.25em; color:#7cc4ff; }}
 .fbox.star b {{ color:#ffd54f; }}
 .fbox.dump b {{ color:#ff6b6b; }}
 .arrow {{ color:#5b6c85; font-size:1.2em; }}
 table {{ border-collapse:collapse; width:100%; font-size:0.85em; }}
 th,td {{ border-bottom:1px solid #26324a; padding:4px 8px; text-align:right; }}
 th {{ background:#1c2636; color:#9fb0c8; position:sticky; top:0; }}
 td.nm {{ text-align:left; font-weight:bold; }}
 td.cd {{ color:#e8ecf3; font-weight:bold; letter-spacing:0.5px; }}
 td.td2 {{ text-align:left; font-size:0.85em; color:#7cc4ff; white-space:nowrap; }}
 td.gr {{ text-align:left; font-size:0.9em; }}
 tr.green td.nm {{ color:#69f0ae; }}
 tr.amber td.nm {{ color:#ffd54f; }}
 tr.dump td {{ color:#8a93a5; }}
 tr.dump td.nm {{ color:#ff6b6b; }}
 .pos {{ color:#ff8a80; }} .neg {{ color:#82b1ff; }}
 h2 {{ font-size:1.0em; margin:20px 0 6px; color:#9fb0c8; }}
 .note {{ color:#6b7a92; font-size:0.78em; margin-top:14px; }}
</style></head><body>
<h1>💰 돈흐름도 <span style="font-size:0.7em;color:#9fb0c8">{ts} · 레짐 {html.escape(str(regime))}</span></h1>
<div class="sub">15초마다 자동 새로고침 · 장중 1분마다 데이터 재생성 (읽기전용)
 · <b style="color:#7cc4ff">🔵보유 {len(hold)}종목</b> (투입 {inv:,.0f}원) · <b style="color:{'#69f0ae' if rpnl>=0 else '#ff6b6b'}">오늘 확정 {rpnl:+,.0f}원</b> · 매도완결 {len(done)}종목</div>

<div class="flow">
 <div class="fbox">코스닥 전체<b>~1,700</b></div><div class="arrow">→</div>
 <div class="fbox">거래대금 상위<b>700</b></div><div class="arrow">→</div>
 <div class="fbox">품질필터·정원<br>(50억·2만·1000억)<b>200</b></div><div class="arrow">→</div>
 <div class="fbox">오늘 유니버스<b>{univ}</b></div><div class="arrow">→</div>
 <div class="fbox">돈 몰림 순위<b>{len(rows)}행</b></div><div class="arrow">→</div>
 <div class="fbox star">⭐ 매수세<b>{len(stars)}</b></div>
 <div class="fbox dump">🔴 던짐(금지)<b>{len(dumps)}</b></div><div class="arrow">→</div>
 <div class="fbox">매매기 진입확인<br>(상승 or 저점반등)<b>최대 3보유</b></div>
</div>

<h2>📈 매수세 순위 (돈 몰린 순 · ⭐=큰손 +10억↑) — {len(buys)}종목</h2>
<table>
<tr><th>등수</th><th style="text-align:left">종목</th><th>코드</th><th style="text-align:left">결과</th><th style="text-align:left">매매</th><th>큰손합</th><th>기관</th><th>외인</th><th>프로</th><th>등락</th><th>체결</th><th>거래대금</th><th>⭐</th><th style="text-align:left">등급</th></tr>
{body_rows}
</table>

<h2>🔴 던짐 · 매수금지 (세력이 파는 중 — 순매수 커 보여도 함정) — {len(dumps)}종목</h2>
<table>
<tr><th>등수</th><th style="text-align:left">종목</th><th>코드</th><th style="text-align:left">결과</th><th style="text-align:left">매매</th><th>큰손합</th><th>기관</th><th>외인</th><th>프로</th><th>등락</th><th>체결</th><th>거래대금</th><th>⭐</th><th style="text-align:left">등급</th></tr>
{dump_rows}
</table>

<h2>🌅⚡ 오전 스캘핑 (09:00~10:30 · 저점앵커 진입 → 익절+1.5% 짧게 반복 · 현재 그림자) — 감시 {ms_watch}종목 · 보유 {len(ms_hold)}종목 · 오늘 매도 {len(ms_sells)}건 (합계 {ms_pnl:+.2f}%p)</h2>
<div class="sub">보유중: {html.escape(ms_hold_txt)}</div>
<table>
<tr><th style="text-align:left">시각</th><th style="text-align:left">종목</th><th>코드</th><th style="text-align:left">방향</th><th style="text-align:left">사유</th><th>진입가</th><th>수익</th><th style="text-align:left">모드</th></tr>
{ms_rows}
</table>

<div class="note">깔때기: 코스닥 → 거래대금 상위 700 → 품질필터(거래대금 50억·주가 2만·시총 1000억) 상위 200 → 큰손합(기관+외인+프로그램 순매수) 내림차순 1~60등.<br>
⭐ = 큰손합 +10억 이상 & 던짐 아님. 🔴 던짐 = 한 주체 대량매도(기관/외인 -80억·프로 -100억) 또는 2주체 이상 매도 또는 개미가 크게 받는 중.<br>
매매기: ⭐후보를 순위대로 → 진입확인(오르는 중 or 체결강도 저점반등) → 역할슬롯(통합대장2·바닥2·MA전환1) → 동시보유 최대 3종목 · 1종목 20만원.</div>
</body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"돈흐름도 생성: {OUT} ({len(rows)}행·★{len(stars)}·던짐{len(dumps)})")

if __name__ == "__main__":
    main()
