# -*- coding: utf-8 -*-
"""캡틴2 저녁 자동정산 v1 — 2026-07-22 친구님 "내일은 힘들어·할 수 있는 거 다 해줘".

장 마감 후(15:45) 자동 실행 — 사람 없이도 하루 성적표를 바탕화면에 남긴다.
  ① 캡틴2: 레인별(RAID/PULL) 왕복 성적·매도사유 분포·PULL 거래별 양식
     (저점 대비 매수가·신저점→RESET·RESET→BUY·2분 MFE/MAE — 초단위 재생 CSV 사용)
  ② 골짜기: 매수 시도/차단/체결·관망 판정 분포(반등품질 통과율 재료)
  ③ 시스템: 차단 깃발·크래시 스탬프·재기동 횟수
읽기 전용(주문 0·TR 0). 출력: 바탕화면 캡틴2_저녁정산.txt + data\LOG 누적.
"""
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(r"C:\stock_bot")
TODAY = datetime.now().strftime("%Y%m%d")
NOW = datetime.now()
COST = 0.469

OUT_LOG = BASE / "data" / "LOG" / f"captain2_evening_report_{TODAY}.txt"
OUT_DESKTOP = Path(r"C:\Users\UserK\Desktop") / "캡틴2_저녁정산.txt"

L = [f"════ 캡틴2 저녁 자동정산 {NOW:%Y-%m-%d %H:%M} ════", ""]

# ── ① 캡틴2 레인별 성적 ─────────────────────────────────────────
try:
    ev_path = BASE / "data" / "shadow" / f"captain2_events_{TODAY}.csv"
    rows = list(csv.DictReader(ev_path.open(encoding="utf-8-sig"))) if ev_path.exists() else []
    open_buy = {}
    trades = []
    for r in rows:
        e = r["event"]
        if e in ("BUY", "SHADOW_FILL"):
            open_buy[r["code"]] = r
        elif e in ("SELL", "SHADOW_SELL_FILL") and r["code"] in open_buy:
            b = open_buy.pop(r["code"])
            trades.append((b, r))
    if not trades:
        blocked = sum(1 for r in rows if r["event"] == "BUY_BLOCKED")
        L.append(f"[캡틴2] 완결 왕복 0건 (이벤트 {len(rows):,}행·매수차단 {blocked}건) — 깃발/모드 확인")
    else:
        L.append(f"[캡틴2] 왕복 {len(trades)}건")
        for lane in ("RAID", "PULL"):
            g = [(b, s) for b, s in trades if (b.get("lane") or "RAID") == lane]
            if not g:
                L.append(f"  {lane}: 0건")
                continue
            pnls = [(float(s["price"]) / float(b["price"]) - 1) * 100 for b, s in g]
            w = len([p for p in pnls if p > 0])
            L.append(f"  {lane}: {len(g)}건 승률 {w/len(g)*100:.0f}% 평균 {sum(pnls)/len(g):+.2f}% "
                     f"합계 {sum(pnls):+.2f}% 비용후 {sum(pnls)-len(g)*COST:+.2f}%")
        why = Counter()
        for _, s in trades:
            rs = str(s.get("reason") or "")
            key = ("트레일" if "TRAIL" in rs else "돈마름" if "DRYUP" in rs
                   else "흐름매도" if "FLOW_WEAK" in rs else "하드손절" if "HARD_STOP" in rs
                   else "강제청산" if "TIME_EXIT" in rs else "기타")
            why[key] += 1
        L.append(f"  매도 사유: {dict(why)}")
        # PULL 거래별 양식 (2분 MFE/MAE = 재생 CSV)
        pulls = [(b, s) for b, s in trades if (b.get("lane") or "") == "PULL"]
        if pulls:
            rp = defaultdict(list)
            rp_path = BASE / "data" / "shadow" / "captain2_replay" / f"captain2_1s_{TODAY}.csv"
            if rp_path.exists():
                with rp_path.open(encoding="utf-8-sig") as fh:
                    for r in csv.DictReader(fh):
                        try:
                            rp[r["code"]].append((r["ts"], float(r["current_price"])))
                        except (ValueError, KeyError):
                            pass
            L.append("  [PULL 거래별 — 친구님 양식] (저점+1.5% 초과 매수 = 추격 판정)")
            chase = 0
            for b, s in pulls:
                e = float(b["price"])
                low = float(b.get("reset_price") or 0)
                vs_low = (e / low - 1) * 100 if low > 0 else 0
                if vs_low > 1.5:
                    chase += 1
                t0 = datetime.fromisoformat(b["ts"])
                seg = [p for ts, p in sorted(rp.get(b["code"], []))
                       if b["ts"] <= ts <= (t0 + timedelta(seconds=120)).isoformat(sep=" ")]
                mfe = (max(seg) / e - 1) * 100 if seg else 0
                mae = (min(seg) / e - 1) * 100 if seg else 0
                pnl = (float(s["price"]) / e - 1) * 100
                L.append(f"    {b['ts'][11:16]} {b['name']} 손익 {pnl:+.2f}% | 저점比 {vs_low:+.2f}% | "
                         f"2분 MFE {mfe:+.2f}/MAE {mae:+.2f}")
            L.append(f"    추격화(저점+1.5%↑): {chase}/{len(pulls)}건 — 많으면 성공 아님(친구님 기준)")
except Exception as e:
    L.append(f"[캡틴2] 정산 실패: {e}")

# ── ①-2 수급 관찰 (D-1·D-2 기관/외인 — 2026-07-23 친구님 지시·관찰전용) ──────────
#   종가매수 검증(supply_signal 7/1 백테: 기관 D-2 최강·D-1 역신호·외인 노이즈)이
#   당일 대장주에도 통하는지 실측하는 기록. 소스=investor_daily.csv(opt10059).
#   프로그램 매매는 일별 소스 없음(제외). 매매 판단 무접촉 — 집계·표시만.
try:
    inv_by, inv_dates = {}, set()
    inv_path = BASE / "data" / "investor_daily.csv"
    if inv_path.exists():
        with inv_path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                c = str(r.get("code", "")).zfill(6)
                d = str(r.get("date", "")).strip()
                if not c or not d:
                    continue
                try:
                    inst = int(float(str(r.get("inst_net") or 0).replace(",", "")))
                except (ValueError, TypeError):
                    inst = None
                try:
                    frgn = int(float(str(r.get("foreign_net") or 0).replace(",", "")))
                except (ValueError, TypeError):
                    frgn = None
                inv_by[(c, d)] = (inst, frgn)
                inv_dates.add(d)
    if trades and inv_by:
        allsess = sorted(inv_dates | {TODAY})
        i = allsess.index(TODAY)
        d1 = allsess[i - 1] if i >= 1 else None
        d2 = allsess[i - 2] if i >= 2 else None
        fv = lambda v: f"{v:+,}" if v is not None else "-"
        L.append("")
        L.append(f"[수급 관찰 — 기록전용] D-1={d1} · D-2={d2} (기관/외인 순매수, 단위=주)")
        groups = defaultdict(list)
        nodata = 0
        for b, s in trades:
            c = str(b["code"]).zfill(6)
            pnl = (float(s["price"]) / float(b["price"]) - 1) * 100
            i1 = inv_by.get((c, d1)) if d1 else None
            i2 = inv_by.get((c, d2)) if d2 else None
            if i1 is None and i2 is None:
                nodata += 1
                continue
            inst1, f1 = (i1 if i1 else (None, None))
            inst2, f2 = (i2 if i2 else (None, None))
            L.append(f"    {b['ts'][11:16]} {b['name']} {pnl:+.2f}% | "
                     f"기관 D-1 {fv(inst1)} · D-2 {fv(inst2)} | "
                     f"외인 D-1 {fv(f1)} · D-2 {fv(f2)}")
            for key, v in (("D-2 기관", inst2), ("D-1 기관", inst1),
                           ("D-2 외인", f2), ("D-1 외인", f1)):
                if v is not None:
                    groups[(key, v > 0)].append(pnl)

        def _grp(g):
            if not g:
                return "0건"
            w = len([p for p in g if p > 0])
            return f"{len(g)}건 승률 {w / len(g) * 100:.0f}% 평균 {sum(g) / len(g):+.2f}%"
        for key in ("D-2 기관", "D-1 기관", "D-2 외인", "D-1 외인"):
            L.append(f"  {key} 매집(+): {_grp(groups.get((key, True), []))}"
                     f"  vs  비매집: {_grp(groups.get((key, False), []))}")
        if nodata:
            L.append(f"  수급 데이터 없는 왕복: {nodata}건 (수집 유니버스 밖)")
        L.append("  ※ 판정 반영 아님 — 며칠 누적 후 차이 확인되면 순위 가점/관문 결정(친구님)")
except Exception as e:
    L.append(f"[수급 관찰] 실패: {e}")

# ── ② 골짜기 ────────────────────────────────────────────────────
try:
    vlog = BASE / "data" / "LOG" / "valley_hunter_live.log"
    txt = vlog.read_text(encoding="utf-8", errors="replace") if vlog.exists() else ""
    today_tag = NOW.strftime("%Y%m%d")
    lines = [ln for ln in txt.splitlines() if ln.startswith(f"[{today_tag}")]
    n_watch = sum(1 for ln in lines if "관망" in ln)
    n_block = sum(1 for ln in lines if "manual_buy_block" in ln)
    # ★[2026-07-24] 실제 로그 문구로 교정 — 종전 "✅매수체결/✅매도체결"은 로그에 없는 문구라
    #   7/23 응집폭발 6왕복 전부 체결됐는데도 "체결 0"으로 오보(🔥는 세션 배너까지 세서 시도 부풀림).
    n_try = sum(1 for ln in lines if "BLOCKED" in ln or "[LIVE] BUY" in ln)
    n_fill = sum(1 for ln in lines if "✅체결확인" in ln)
    n_sell = sum(1 for ln in lines if "✅매도 체결확인" in ln)
    reasons = Counter()
    for ln in lines:
        m = re.search(r"\[(반등품질혼재|관찰기간워밍업|반등구간초과대기)\]", ln)
        if m:
            reasons[m.group(1)] += 1
    L.append("")
    L.append(f"[골짜기] 관망 {n_watch:,}건 · 매수시도 {n_try} · 깃발차단 {n_block} · "
             f"매수체결 {n_fill} · 매도체결 {n_sell}")
    if reasons:
        tot = sum(reasons.values())
        L.append(f"  관망 사유: " + " · ".join(f"{k} {v}({v/tot*100:.0f}%)" for k, v in reasons.most_common()))
        L.append(f"  → 반등품질 통과율(시도/관망): {n_try}/{n_watch or 1} — 낮으면 관문 과보수 신호(7/22 감사)")
except Exception as e:
    L.append(f"[골짜기] 정산 실패: {e}")

# ── ③ 시스템 상태 ───────────────────────────────────────────────
try:
    L.append("")
    flags = [f for f in ("manual_buy_block.flag", "captain2_off.flag", "valley_off.flag")
             if (BASE / "config" / f).exists()]
    L.append(f"[시스템] 차단 깃발: {', '.join(flags) if flags else '없음'}")
    crash = BASE / "LOG" / "captain2_crash.log"
    if crash.exists():
        stamps = [ln for ln in crash.read_text(encoding="utf-8", errors="replace").splitlines()
                  if "기동" in ln and NOW.strftime("%Y-%m-%d") in ln]
        L.append(f"  캡틴2 오늘 기동 {len(stamps)}회 (1회=정상·2회↑=장중 재기동 발생, crash log 확인)")
except Exception as e:
    L.append(f"[시스템] 점검 실패: {e}")

L.append("")
L.append("(자동 생성 — 상세 분석·비교표는 세션에서 \"정산해\"라고 하면 수행)")
text = "\n".join(L) + "\n"
OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
with OUT_LOG.open("a", encoding="utf-8-sig") as fh:
    fh.write(text + "\n")
try:
    OUT_DESKTOP.write_text(text, encoding="utf-8-sig")
except Exception:
    pass
print(text)
