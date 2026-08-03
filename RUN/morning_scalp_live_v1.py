# -*- coding: utf-8 -*-
"""🌅⚡ 오전 스캘핑 매매기 — ★신설(기본 그림자·주문0)  [2026-07-17]

친구님 확정 전략(오전 09:00~10:30):
  유니버스 : ★새로 안 만듦 — crash_flow_live_v1._crash_map() 그대로 재사용(친구님 "우리 선별기에서
             뽑으면 되지 않을까"). 돈맥 선별기(money_flow_board)가 실시간으로 만드는 코스닥·1만원↑·
             전일거래대금 700억~2조(CF_PVAL_MIN/MAX 공용)·이미 -DROP%↓ 저점 찍은 종목 풀 = "변동성 크고
             거래대금 몰리는 곳"을 이미 걸러주고 있어서 별도 랭킹 로직이 필요 없다.
  매수     : ★[7/17 밤 4차 — 친구님 [UNIVERSAL VALLEY SCALPING ENGINE] 원안·급락주와 완전 분리]
             valley_scalp_buy_v1.ValleyAnchor(스캘핑 전용) — armed 없음(모든 반등 구간), 신저점마다
             앵커 생성+체결량·Delta·seg_che 전부 0 리셋 → 30초 새 체결만 분석 → 6조건 동시충족 매수:
             seg_che≥105(VS_SEG_CHE_TH) ∧ 매수≥매도 ∧ Delta증가 ∧ VEL증가 ∧ ACC증가 ∧ 저점+0.8~1.5%.
             손절 = 매수가 -1%(MS_STOP) 즉시 전량 → 새 저점앵커 재관찰(계단·최대 MS_REBUY_MAX=2회).
  매도     : ★[7/17 밤 3차 확정 — 친구님 원안 [SCALPING SELL ENGINE] 그대로. 3단 분할은 친구님 기각
             ("스캘핑은 몇 분 만에 끝나는데 뭘 1·2·3단으로 나누냐") — 고정 익절/분할 전부 삭제]
             목표: 최고점을 예측하지 말고, 고점이 '확인'될 때 전량 매도한다.
             ① 고점 후보(신고점) 발생 → 앵커 생성, 동시에 매수/매도체결량·Delta·구간체결강도 전부 0 리셋
             ② 앵커 이후 새 체결만 MS_ANCHOR_OBS_SEC(기본 25초) 동안 분석
             ③ 보유 유지 = seg_che≥문턱 ∧ 매수>매도 ∧ 고점 계속 갱신
             ④ 전량 매도 = seg_che < MS_SEG_CHE_TH(기본105) ∧ 매도>매수 (관찰시간 경과 후 판정)
                + 직전 저점(앵커 이후 최저가) 이탈 ∧ 매도우위 → 전량 매도 (보조 확인)
             절대규칙: 앵커마다 체결량 리셋·과거 체결량 사용 금지·고정 수익률(+3%/+5%) 매도 금지·
                       가격보다 체결량과 수급 우선. (매수엔진 저점앵커와 완전 대칭 구조)
             안전판: 재난손절 -4%(MS_STOP)·60분 타임아웃·엔진종료청산만 유지(친구님 스펙 외 최소한).
  ⚠️1분봉 백테로는 이 설계를 판정할 수 없음(20~30초 구간 체결량이 핵심인데 1분봉+틱룰은 음봉=전량매도로
     뭉개져 문턱 100~115가 전부 동일 결과) — 검증은 그림자 2초 실데이터로만 한다. 문턱 튜닝은
     setx MS_SEG_CHE_TH 100/105/110/115 (코드 수정 없이).

■ ★안전 (crash_flow_live_v1과 동일 구조 — _cur/_cum_vol/_fills_qty/_gate_ok/_crash_map 그대로 재사용)
  MS_LIVE=NO 가 기본 = 실주문 0(그림자). 라이브 전환은 cmd에 MS_LIVE=YES 명시 + ONLY_MF_ALLOW에 MSCALP 추가 필요
  (이 관문에 안 넣으면 LIVE=YES여도 브로커가 조용히 거부 — 7/14 잡주사고 교훈, 의도적 이중 안전장치).
  끄기 = config\\morning_scalp_off.flag 생성(다음 기동부터 그림자).
  장중 즉시정지 = config\\manual_buy_block.flag(매수만 차단, 보유분 매도는 계속).
  주문 격리 rqname=MSCALP_ (급락주·아침대장·종가매수와 완전 분리, 자본도 독립 — shared_slots 미사용).
  ★선별기 풀을 공유하지만 매수/매도 주문 실행은 이 엔진이 독립적으로 판단·처리 — crash_flow와 같은 종목을
    동시에 서로 다른 이유로 매수할 수 있음(포지션 격리는 각자 ledger로 됨. 실주문 켤 때 총 노출액 재검토 필요).

■ 스위치
  MS_LIVE=NO              실주문 여부(기본 그림자)
  MS_CAP / MS_SLOTS       종목당 금액(기본 SAFEPLUS_CAP_KRW=30만) / 동시보유 최대(기본3)
  MS_STOP                 재난손절%(-4·안전판)
  MS_SEG_CHE_TH           구간체결강도 매도문턱(기본105 — setx로 100/110/115 튜닝)
  MS_ANCHOR_OBS_SEC       앵커 후 관찰 최소시간(초·기본25)
  MS_ENTRY / MS_ENTRY_END 진입창(0900~1030)
  MS_TIMEOUT_MIN          강제청산까지 최대 보유(분, 60)
  선별기 풀 문턱(CF_PVAL_MIN/MAX·CF_DROP 등)과 저점앵커 세부 문턱(LA_*)은 각각
  crash_flow_live_v1.py(선별기 풀) / valley_scalp_buy_v1.py(매수 세부 VS_*·스캘핑 전용) 참고.
"""
import os, sys, csv, json, time, uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
# ★[7/17 밤 4차] 매수 = valley_scalp_buy_v1(스캘핑 전용·UNIVERSAL VALLEY) — 친구님 "급락주하고 같으면 안 돼"
#   급락주 공용이던 low_anchor_buy_v1 의존 완전 제거. 선별기/시세/체결확인은 인프라라 계속 재사용(전략 아님).
from valley_scalp_buy_v1 import va_from_ledger, va_to_ledger
from crash_flow_live_v1 import _crash_map, _cur, _cum_vol, _fills_qty, _gate_ok   # ★[재사용] 선별기+시세+체결확인+관문미러
REBUY_MAX = int(os.environ.get("MS_REBUY_MAX", "2"))   # 손절 후 재관찰 최대 횟수(스캘핑 전용)

LEDGER = Path(os.environ.get("MS_LEDGER") or r"C:\stock_bot\data\morning_scalp_live_ledger.json")
CSVLOG = Path(os.environ.get("MS_CSV") or r"C:\stock_bot\LOG\morning_scalp_live.csv")
LOG = Path(r"C:\stock_bot\data\LOG\morning_scalp_live.log")

LIVE = os.environ.get("MS_LIVE", "NO").strip().upper() == "YES"
if Path(r"C:\stock_bot\config\morning_scalp_off.flag").exists():
    LIVE = False
CAP = float(os.environ.get("MS_CAP") or os.environ.get("SAFEPLUS_CAP_KRW", "300000"))
SLOTS = int(os.environ.get("MS_SLOTS", "3"))
STOP = float(os.environ.get("MS_STOP", "-1.0"))   # ★[UNIVERSAL VALLEY 스펙7] 매수가 -1% 즉시 전량매도
# ★[7/17 친구님 원안] 고점앵커 매도 파라미터 — 문턱은 실데이터 튜닝 대상(setx로 코드수정 없이)
SEG_CHE_TH = float(os.environ.get("MS_SEG_CHE_TH", "105"))       # 구간체결강도(매수/매도×100) 이 미만 ∧ 매도>매수 = 전량매도
ANCHOR_OBS_SEC = float(os.environ.get("MS_ANCHOR_OBS_SEC", "25"))  # 앵커 생성 후 새 체결 분석 최소시간(초·20~30초 스펙)
ENTRY_HM = os.environ.get("MS_ENTRY", "0900")
ENTRY_END = os.environ.get("MS_ENTRY_END", "1030")
TIMEOUT_MIN = float(os.environ.get("MS_TIMEOUT_MIN", "60"))
FILL_WAIT = float(os.environ.get("MS_FILL_WAIT", "8"))
LOOP_SEC = float(os.environ.get("MS_LOOP_SEC", "2"))
RUN_SEC = float(os.environ.get("MS_RUN_SEC", "5700"))   # 09:00~10:35 커버(95분)

COLS = ["일자", "시각", "종목코드", "종목명", "방향", "사유", "진입가", "현재가", "수익퍼센트",
        "재관찰회차", "실전여부", "주문결과", "매수비율"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _jload(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d if d is not None else {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _csv_row(r):
    try:
        CSVLOG.parent.mkdir(parents=True, exist_ok=True)
        new = not CSVLOG.exists()
        with CSVLOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"CSV 실패: {e}")


class Trader:
    def __init__(self):
        self.bc = None; self.acc = ""

    def connect(self):
        if not LIVE:
            return True
        try:
            from broker_client import BrokerClient, is_broker_alive
            if not is_broker_alive():
                _log("🚨 브로커 죽음 → 주문 불가"); return False
            self.bc = BrokerClient()
            ai = self.bc.account_info("ACCNO")
            accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
            if isinstance(accs, str):
                accs = [a for a in accs.split(";") if a]
            self.acc = (accs[0] if isinstance(accs, list) and accs else "") \
                or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()
            return bool(self.acc) or (_log("🚨 계좌 없음") or False)
        except Exception as e:
            _log(f"🚨 브로커 연결 실패: {e}"); return False

    def order(self, code, qty, side):
        if not LIVE:
            _log(f"  [그림자] {side} {code} x{qty}")
            return "SHADOW"
        if side == "BUY" and Path(r"C:\stock_bot\config\manual_buy_block.flag").exists():
            _log("  🛑 manual_buy_block.flag → 매수 차단"); return "BLOCKED"
        try:
            r = self.bc.send_order_real(
                idempotency_key=f"mscalp_{side.lower()}_{code}_{uuid.uuid4()}",
                account=self.acc, code=code, qty=int(qty),
                order_type=(1 if side == "BUY" else 2), price=0,
                hoga_gb="06", rqname=f"MSCALP_{side}_{code}", screen_no="9752")
            st = str((r or {}).get("status", "")).upper()
            _log(f"  [LIVE] {side} {code} x{qty} → {st}")
            return st or "NONE"
        except Exception as e:
            _log(f"  🚨 주문 실패 {side} {code}: {e}"); return "ERROR"


def _open_positions(led):
    return sum(1 for v in led["codes"].values() if isinstance(v, dict) and v.get("position"))


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < ENTRY_HM or hm > ENTRY_END:
        _log(f"진입창({ENTRY_HM}~{ENTRY_END}) 밖 — 종료"); return
    _log("=" * 70)
    _log(f"🌅⚡ 오전 스캘핑 {'★실전(LIVE)' if LIVE else '그림자(주문0)'} — "
         f"선별기 풀 재사용·익절+{TP:g}% 손절{STOP:g}% 진입창{ENTRY_HM}~{ENTRY_END} "
         f"타임아웃{TIMEOUT_MIN:g}분 {CAP:,.0f}원×{SLOTS}슬롯")

    led = _jload(LEDGER, {})
    if led.get("date") != today:
        led = {"date": today, "codes": {}}

    trader = Trader()
    if not trader.connect():
        return

    deadline = time.monotonic() + RUN_SEC
    while time.monotonic() < deadline:
        now = datetime.now(); hm = now.strftime("%H%M"); t = time.time()
        if hm > ENTRY_END and _open_positions(led) == 0:
            break
        dirty = False
        cm = _crash_map()   # ★선별기 실시간 풀(700억~2조·이미 저점 찍은 종목) — crash_flow와 동일 소스
        for code, info in cm.items():
            entry = led["codes"].get(code, {})
            if entry.get("done"):
                continue
            cur = _cur(code)
            if cur <= 0:
                continue
            pos = entry.get("position")
            if pos:
                ret_pct = (cur / pos["entry_px"] - 1) * 100
                hold_min = (t - pos["entry_ts"]) / 60.0
                nm = info.get("name", code)

                # ── ★친구님 원안 [SCALPING SELL ENGINE] — 고점앵커 + 구간 체결량으로 고점 '확인' 후 전량매도 ──
                why = None
                if ret_pct <= STOP:
                    why = "재난손절"                       # 안전판(스펙 외 최소한)
                elif hold_min >= TIMEOUT_MIN:
                    why = "타임아웃청산"                    # 안전판(스펙 외 최소한)
                else:
                    cv = _cum_vol(code)
                    if cur > pos.get("peak", 0):
                        # 고점 후보 발생 → 앵커 생성 + 체결량·Delta 전부 0 리셋(절대규칙)
                        # 직전 앵커 구간의 최저가는 '직전 저점'으로 보존(저점이탈 판정용)
                        pos["swing_low"] = pos.get("anchor_low")
                        pos["peak"] = cur; pos["anchor_ts"] = t; pos["anchor_low"] = cur
                        pos["seg_buy"] = 0.0; pos["seg_sell"] = 0.0
                        pos["last_cum_vol"] = cv; pos["last_px"] = cur; pos["last_dir"] = 0
                        dirty = True
                    else:
                        pos["anchor_low"] = min(pos.get("anchor_low", cur), cur)
                        # 앵커 이후 새 체결만 누적 — 틱룰 근사(가격 오르면 매수/내리면 매도·LowAnchor._seg_update와 동일)
                        lp = pos.get("last_px"); lcv = pos.get("last_cum_vol")
                        if lp is not None and cv is not None and lcv is not None:
                            dv = max(0.0, cv - lcv)
                            d = pos.get("last_dir", 0)
                            if cur > lp:
                                d = 1
                            elif cur < lp:
                                d = -1
                            if d > 0:
                                pos["seg_buy"] = pos.get("seg_buy", 0.0) + dv
                            elif d < 0:
                                pos["seg_sell"] = pos.get("seg_sell", 0.0) + dv
                            pos["last_dir"] = d
                        pos["last_px"] = cur
                        if cv is not None:
                            pos["last_cum_vol"] = cv
                        dirty = True
                        sb, ss = pos.get("seg_buy", 0.0), pos.get("seg_sell", 0.0)
                        seg_che = (sb / ss * 100) if ss > 0 else 999.0
                        sell_dom = ss > sb and seg_che < SEG_CHE_TH   # 매도>매수 ∧ 구간체결강도<문턱
                        elapsed = t - pos.get("anchor_ts", t)
                        if elapsed >= ANCHOR_OBS_SEC and sell_dom:
                            why = f"고점확인매도(che{seg_che:.0f}·매도{ss:.0f}>매수{sb:.0f})"
                        elif (pos.get("swing_low") and cur < pos["swing_low"] and ss > sb):
                            why = f"저점이탈매도(직전저점{pos['swing_low']:,.0f}·che{seg_che:.0f})"

                if why:
                    st = trader.order(code, pos["qty"], "SELL")
                    if not LIVE or FILL_WAIT <= 0 or _fills_qty(code, pos["entry_hms"], "매도") > 0 or st == "SHADOW":
                        _log(f"  {'🔻' if '손절' in why else '💰'}{why} {nm}({code}) "
                             f"{pos['entry_px']:,.0f}→{cur:,.0f} ({ret_pct:+.2f}%) x{pos['qty']} [{st}]")
                        _csv_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                                   "종목명": nm, "방향": "SELL", "사유": why, "진입가": pos["entry_px"],
                                   "현재가": cur, "수익퍼센트": round(ret_pct, 2),
                                   "재관찰회차": pos.get("n_rebuys", 0),
                                   "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": st})
                        entry["position"] = None
                        # ★[UNIVERSAL VALLEY] -1% 손절 후에도 재관찰 — "다시 저점 가길 기다리며 반복해
                        #   최저점을 발굴"(친구님 계단 원칙). 종목당 재시도는 MS_REBUY_MAX(2회)까지.
                        entry["n_rebuys"] = pos.get("n_rebuys", 0) + (1 if "손절" in why else 0)
                        if entry["n_rebuys"] >= REBUY_MAX and "손절" in why:
                            entry["done"] = True   # 손절 2회 = 그 종목 오늘 포기
                        elif why == "타임아웃청산":
                            entry["done"] = True   # 시간 다 쓴 종목은 재진입 없음
                        else:
                            entry.pop("va", None)   # 새 저점앵커부터 재관찰
                        dirty = True
                led["codes"][code] = entry
                continue
            # ── ★[UNIVERSAL VALLEY] 매수 판정 — 스캘핑 전용 ValleyAnchor(armed 없음·모든 반등 구간) ──
            va = va_from_ledger(code, entry.get("va", {}))
            cv = _cum_vol(code)
            ev = va.feed(cur, cv, t)
            entry["va"] = va_to_ledger(va)
            dirty = True
            if ev and ev["signal"] == "BUY":
                if not _gate_ok(code, cur):
                    _log(f"  ⛔관문미달(가격/시총) {info.get('name', code)}({code}) — 건너뜀")
                    entry["done"] = True; led["codes"][code] = entry; continue
                if LIVE and SLOTS - _open_positions(led) <= 0:
                    led["codes"][code] = entry; continue
                qty = max(1, int(CAP // cur))
                st = trader.order(code, qty, "BUY")
                filled = True
                if LIVE and FILL_WAIT > 0 and st not in ("SHADOW",):
                    time.sleep(FILL_WAIT)
                    filled = _fills_qty(code, hm + ":00", "매수") > 0
                if not filled:
                    _log(f"  👻유령매수(체결0) {info.get('name', code)}({code}) — 취소·미보유 유지")
                    entry["done"] = True
                else:
                    # 매수 즉시 매도쪽 첫 앵커 생성(고점=진입가·카운터 0) — 이후 신고점마다 리셋
                    entry["position"] = {"entry_px": cur, "entry_ts": t, "entry_hms": hm + ":00", "qty": qty,
                                          "n_rebuys": entry.get("n_rebuys", 0),
                                          "peak": cur, "anchor_ts": t, "anchor_low": cur, "swing_low": None,
                                          "seg_buy": 0.0, "seg_sell": 0.0,
                                          "last_cum_vol": cv, "last_px": cur, "last_dir": 0}
                    nm = info.get("name", code)
                    # 화면 표시(스펙8): CHE·BUY VOL·SELL VOL·DELTA·VEL·ACC
                    _log(f"  💰매수 {nm}({code}) 저점{ev['low']:,.0f}→{cur:,.0f} | "
                         f"CHE:{ev['seg_che']:.0f}↑ BUY:{ev['buy_vol']:,} SELL:{ev['sell_vol']:,} "
                         f"DELTA:{ev['delta']:+,}{'↑' if ev['delta_up'] else ''} "
                         f"VEL:{'↑' if ev['vel_up'] else '-'} ACC:{'↑' if ev['acc_up'] else '-'} [{st}]")
                    _csv_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                               "종목명": nm, "방향": "BUY", "사유": f"valley(che{ev['seg_che']:.0f})",
                               "진입가": cur, "현재가": cur,
                               "수익퍼센트": 0, "재관찰회차": entry.get("n_rebuys", 0),
                               "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": st,
                               "매수비율": ev["seg_che"]})
                led["codes"][code] = entry
        if dirty:
            _jsave(LEDGER, led)
        time.sleep(LOOP_SEC)

    # ★엔진 종료 청산 — 잔량(runner)이 남은 채 엔진이 끝나면 관리자가 없어짐(매도 유령 사각).
    #   백테의 '장마감 라이딩'은 3/392건뿐이라 실익 대비 무관리 위험이 커서 종료 시점 전량 정리.
    for code, entry in led["codes"].items():
        pos = entry.get("position") if isinstance(entry, dict) else None
        if not pos:
            continue
        cur = _cur(code)
        st = trader.order(code, pos["qty"], "SELL")
        ret_pct = (cur / pos["entry_px"] - 1) * 100 if cur > 0 else 0.0
        _log(f"  🏁엔진종료청산 {code} x{pos['qty']} ({ret_pct:+.2f}%) [{st}]")
        _csv_row({"일자": today, "시각": datetime.now().strftime("%H:%M:%S"), "종목코드": code,
                   "종목명": code, "방향": "SELL", "사유": "엔진종료청산", "진입가": pos["entry_px"],
                   "현재가": cur, "수익퍼센트": round(ret_pct, 2),
                   "재관찰회차": pos.get("n_rebuys", 0),
                   "실전여부": "LIVE" if LIVE else "SHADOW", "주문결과": st})
        entry["position"] = None
        entry["done"] = True
    _jsave(LEDGER, led)
    _log("=== 오전 스캘핑 종료 ===")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
