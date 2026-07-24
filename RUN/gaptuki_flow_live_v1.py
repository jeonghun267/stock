# -*- coding: utf-8 -*-
"""🚀💰 횡보 후 갑툭이(자금유입) — 실전 매매기 v1
[2026-07-20 친구님 "실전배치하라고" 명시 지시 — 그림자와 병행 가동]

⚠️ 배경(정직 기록): 실전형 진입 백테 3종은 비용 후 마이너스였고(토픽메모리 참조),
  지침서는 Shadow→검증→실전이었으나 친구님이 명시적으로 즉시 실전 배치를 지시.
  → 첫날 안전판: 1주 사이징(GL_QTY_FIX=1)·3슬롯·킬스위치·체결확인 전배선.

감지 = gaptuki_flow_shadow_v1.Flow 상태기계 그대로 import (단일 소스 — 5단계:
  횡보→갑툭이(대금·거래량·체결강도 동시)→자금검증→눌림→재출발). 후보 확정 순간 실매수.
매수 = 시장가 1주 (최유리지정가 아님 — 7/16 기가레인 VI 중 최유리 거부 사례 회피),
  rqname GAPTUKI_BUY_* (ONLY_MF_ALLOW에 GAPTUKI 필요 — 배선 시 setx),
  접수OK≠체결: fills_YYYYMMDD.csv 체결확인(FILL_WAIT초) → 미체결 전량취소 → 실패 기록.
매도 사슬(전략 독립 출구 — vol_exit 통일정책 대상 아님, 골짜기 방식):
  ①하드손절: 진입가 -2% (트레일 무장 전)
  ②트레일링: +1% 도달 시 무장 → 고점 -1% 이탈 시 전량매도 (꼭대기까지 끌고가기 — 친구님 지시)
  ③시간청산: 진입 후 120분
  ④장청산: 15:10 전량 → 15:12 종료. 전용 FLAT 태스크(15:14)가 엔진 재실행(잔여 매도 안전판)
  매도도 체결확인(pending_sell) → 미체결취소 → 재매도(최대 3회).
킬스위치: config\gaptuki_off.flag → 다음 기동부터 주문0(감지·기록만).
  장중 즉시정지 = config\manual_buy_block.flag (매수차단·매도는 계속 — 전 엔진 공용).
산출: data\gaptuki_flow_live_ledger.json(장부·재기동 이어받기) · data\gaptuki_flow_live_trades.csv
★[2026-07-20 지침서3 안정화] ①entry/손익 = fills 실제 평균체결가(신호가와 혼용 금지·signal_px는 참고 기록)
  ②후보 선삭제 금지 — 접수 성공 후에만 CONSUMED(슬롯부족·1회 거부는 FOLLOW 유지·재시도, 구조적 실패만 사유기록 종료)
  ③GL_LIVE 기본값 NO(env 없으면 무조건 그림자 — cmd가 YES 명시) ④리허설 주입구 GL_LEDGER/GL_TRADES.
★[2026-07-20 지침서4 부분체결 안전화] 매수: 1주↑ 체결이면 PARTIAL_BUY로 실체결수량·가중평균가 등록
  (미체결만 취소) / 매도: 잔량만 재매도(PARTIAL_SELL·전량 재주문 금지) / 장부수량 = 항상 실체결수량.
  전략·손절·트레일·FOLLOW·슬롯 불변. 리허설 주입구 GL_FILLS_DIR 추가.
스위치: GL_QTY_FIX=1 GL_SLOTS=3 GL_STOP=-2.0 GL_TRAIL_ARM=1.0 GL_TRAIL=1.0 GL_HOLD_MAX=120
  GL_ENTRY_END=1430 GL_EXIT=1510 GL_END=1512 GL_FILL_WAIT=8 GL_RUN_SEC=0
"""
import os, sys, csv, json, time, uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")
from gaptuki_flow_shadow_v1 import Flow, load_ma_gap, SNAP, PXMIN  # 감지부 단일 소스

LEDGER = Path(os.environ.get("GL_LEDGER") or r"C:\stock_bot\data\gaptuki_flow_live_ledger.json")   # 리허설 주입구
TRADES = Path(os.environ.get("GL_TRADES") or r"C:\stock_bot\data\gaptuki_flow_live_trades.csv")    # 리허설 주입구
LOG    = Path(r"C:\stock_bot\data\LOG\gaptuki_flow_live.log")
SHARES_CSV = Path(r"C:\stock_bot\DATA\shares_outstanding.csv")

# ★[2026-07-20 지침서3] 기본값 NO — 환경변수 없으면 무조건 그림자. GL_LIVE=YES일 때만 실주문(cmd가 명시 설정).
LIVE = os.environ.get("GL_LIVE", "NO").upper() == "YES"
if Path(r"C:\stock_bot\config\gaptuki_off.flag").exists():
    LIVE = False
QTY       = int(os.environ.get("GL_QTY_FIX", "1"))
SLOTS     = int(os.environ.get("GL_SLOTS", "3"))
STOP      = float(os.environ.get("GL_STOP", "-2.0"))
TRAIL_ARM = float(os.environ.get("GL_TRAIL_ARM", "1.0"))
TRAIL     = float(os.environ.get("GL_TRAIL", "1.0"))
HOLD_MAX  = float(os.environ.get("GL_HOLD_MAX", "120")) * 60.0
ENTRY_END = os.environ.get("GL_ENTRY_END", "1430")
EXIT_HM   = os.environ.get("GL_EXIT", "1510")
END_HM    = os.environ.get("GL_END", "1512")
FILL_WAIT = float(os.environ.get("GL_FILL_WAIT", "8"))
RUN_SEC   = float(os.environ.get("GL_RUN_SEC", "0"))
POLL      = float(os.environ.get("GL_POLL", "1.0"))
START_HM  = os.environ.get("GL_START", "0900")
GATE_MINP  = float(os.environ.get("SAFEPLUS_MIN_PRICE", "1000"))
GATE_MINMC = float(os.environ.get("SAFEPLUS_MIN_MARKETCAP", "0"))

TCOLS = ["일자", "시각", "종목코드", "동작", "가격", "수량", "사유", "수익퍼센트"]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _trade(code, act, px, qty, why, pnl=""):
    try:
        new = not TRADES.exists()
        with TRADES.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=TCOLS)
            if new:
                w.writeheader()
            w.writerow({"일자": datetime.now().strftime("%Y%m%d"), "시각": datetime.now().strftime("%H:%M:%S"),
                        "종목코드": code, "동작": act, "가격": round(px, 0), "수량": qty,
                        "사유": why, "수익퍼센트": pnl})
    except Exception as e:
        _log(f"trades 기록 실패: {e}")


def _jload(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


_shares_map = None


def _gate_ok(code, cur):
    """브로커 주문 관문(가격·시총 하한) 미러 — 못 살 종목은 시도 자체를 생략(7/14 사고 클래스 방지)."""
    global _shares_map
    if 0 < cur < GATE_MINP:
        return False
    if GATE_MINMC > 0 and cur > 0:
        if _shares_map is None:
            m = {}
            try:
                with SHARES_CSV.open(encoding="utf-8-sig") as fh:
                    for r in csv.DictReader(fh):
                        try:
                            m[str(r.get("code", "")).zfill(6)] = float(r.get("shares") or 0)
                        except Exception:
                            pass
            except Exception:
                pass
            _shares_map = m
        sh = _shares_map.get(str(code).zfill(6), 0.0)
        if sh > 0 and sh * cur < GATE_MINMC:
            return False
    return True


_FILLS_DIR = Path(os.environ.get("GL_FILLS_DIR") or r"C:\stock_bot\LOG")   # 리허설 주입구(지침서4)


def _fills_avg(code, since_hms, side="매수"):
    """게이트웨이 체결 그라운드트루스(fills_YYYYMMDD.csv) → (총체결수량, 평균체결가).
    ★[지침서3] 신호가 대신 실제 체결가 사용 — fill_qty는 주문별 누적치라 증가분×fill_px로 가중평균."""
    fp = _FILLS_DIR / f"fills_{datetime.now():%Y%m%d}.csv"
    if not fp.exists():
        return 0, 0.0
    code = str(code).zfill(6)
    prev, wsum, total = {}, 0.0, 0
    try:
        with fp.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    if str(r.get("code", "")).strip().zfill(6) != code:
                        continue
                    if side not in str(r.get("otype", "")):
                        continue
                    if "체결" not in str(r.get("state", "")):
                        continue
                    ts = str(r.get("ts", ""))
                    if len(ts) >= 19 and ts[11:19] < since_hms:
                        continue
                    q = int(float(r.get("fill_qty") or 0))
                    px = float(r.get("fill_px") or 0)
                    ono = str(r.get("order_no", "")).strip() or f"?{ts}"
                    inc = q - prev.get(ono, 0)
                    if inc > 0:
                        prev[ono] = q
                        total += inc
                        wsum += inc * px
                except Exception:
                    continue
    except Exception:
        return 0, 0.0
    return total, (wsum / total if total > 0 else 0.0)


class Broker:
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
                idempotency_key=f"gaptukiflow_{side.lower()}_{code}_{uuid.uuid4()}",
                account=self.acc, code=str(code).zfill(6), qty=int(qty),
                order_type=(1 if side == "BUY" else 2), price=0,
                hoga_gb="03", rqname=f"GAPTUKI_{side}_{code}", screen_no="9761")
            st = str((r or {}).get("status", "")).upper()
            _log(f"  [LIVE] {side} {code} x{qty} 시장가 → {st}")
            return st or "NONE"
        except Exception as e:
            _log(f"  🚨 주문 실패 {side} {code}: {e}"); return "ERROR"

    def cancel_open(self, code, buy=True):
        """미체결 전량취소(opt10075) — 골짜기 동일 패턴. fail-open."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1",
                                   "매매구분": "2" if buy else "1",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"GAPTUKI_OPEN_{code}", screen_no="9761", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 조회 실패 {code}: {e}")
            return
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if not ono or rem <= 0:
                    continue
                cr = self.bc.send_order_real(
                    idempotency_key=f"gaptukiflow_cxl_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=(3 if buy else 4), price=0, hoga_gb="00",
                    rqname=f"GAPTUKI_CXL_{code}", screen_no="9761", origin_order_no=ono)
                _log(f"  🧹잔량취소 {code} 주문{ono} x{rem} → {str((cr or {}).get('status','')).upper()}")
            except Exception as e:
                _log(f"  ⚠️취소 실패 {code}: {e}")


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm > END_HM and hm < "1513":
        pass
    _log("=" * 64)
    _log(f"🚀💰 갑툭이 자금유입 LIVE — {'실전' if LIVE else '그림자(off.flag/GL_LIVE=NO)'} · {QTY}주×{SLOTS}슬롯 · "
         f"손절{STOP}%·트레일무장+{TRAIL_ARM}%→고점-{TRAIL}%·{int(HOLD_MAX/60)}분·청산{EXIT_HM}")
    br = Broker()
    if LIVE and not br.connect():
        _log("🚨 브로커 연결 실패 — 종료(워치독/재기동 대기)")
        return
    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "slots": {}}
    ma_gap = load_ma_gap()
    flows, last_seen = {}, {}
    t0 = time.time()
    last_hb = time.time()
    rejects = []          # Flow 상태기계 탈락 기록(그림자 CSV와 별개 — 로그만)

    while True:
        now = datetime.now(); hm = now.strftime("%H%M")
        if (RUN_SEC and time.time() - t0 >= RUN_SEC):
            break
        if hm >= END_HM and not any(s.get("pos") or s.get("pending_sell") for s in L["slots"].values()):
            break
        if hm >= "1519":
            break
        if hm < START_HM:
            time.sleep(1.0); continue
        try:
            snap = json.loads(SNAP.read_text(encoding="utf-8-sig")).get("codes", {})
        except Exception:
            time.sleep(POLL); continue

        for code, v in snap.items():
            try:
                ts = str(v.get("ts") or "")
                if len(ts) < 16 or ts[:10] != now.strftime("%Y-%m-%d"):
                    continue
                px = float(v.get("cur") or 0)
                if px <= 0 or not ("09" <= ts[11:13] <= "15"):
                    continue
                key = (ts, v.get("cur"), v.get("cum_vol"))
                if last_seen.get(code) == key:
                    continue
                last_seen[code] = key
                cv = v.get("cum_vol")
                cv = float(cv) if cv is not None else None

                # ---- 보유/pending 관리 (매 틱) ----
                s = L["slots"].get(code)
                if s:
                    self_manage(br, L, code, s, px, hm)

                # ---- 감지(신규 진입) ----
                if px < PXMIN:
                    continue
                fl = flows.get(code)
                if fl is None:
                    fl = flows[code] = Flow(code, ma_gap.get(code))
                bar = fl.tick(int(ts[11:13]) * 60 + int(ts[14:16]), px, cv)
                if bar is not None and fl.state in ("IDLE", "SPIKE", "PULLBACK"):
                    fl.on_bar(bar, rejects, today)
                if fl.state == "FOLLOW":        # ★지침서2: 구 TRACK — 그림자 모듈과 문자열 동기 필수
                    # ★[지침서3] 후보 선삭제 금지 — 주문 접수 성공 시에만 try_buy 안에서 CONSUMED 전환.
                    #   슬롯부족/일시 주문실패면 FOLLOW 유지(재시도)·구조적 실패(관문/시간/2회실패)는 사유 기록 후 종료.
                    try_buy(br, L, code, px, hm, fl)
            except Exception as e:
                _log(f"⚠️ {code} 루프 오류: {e}")

        if time.time() - last_hb >= 900:
            pos = [c for c, s in L["slots"].items() if s.get("pos")]
            _log(f"💓 감시{len(flows)} 보유{pos} 탈락{len(rejects)}")
            last_hb = time.time()
        time.sleep(POLL)

    _log(f"종료 — 보유 {[c for c, s in L['slots'].items() if s.get('pos')]}")


_try_ts = {}          # 코드별 마지막 시도/로그 시각 (FOLLOW 유지 중 재시도 스로틀)


def try_buy(br, L, code, px, hm, fl):
    """★[지침서3] 순서 고정: FOLLOW 발견 → 주문 접수 성공 → CONSUMED.
    구조적 실패(이미 처리/진입마감/관문/2회실패)만 사유 기록 후 CONSUMED 종료,
    일시적 사유(슬롯부족/주문거부 1회)는 FOLLOW 유지·재시도(5초 스로틀)."""
    s = L["slots"].get(code) or {}
    if s.get("pos") or s.get("pending_buy") or s.get("done"):
        fl.state = "CONSUMED"                    # 이미 처리된 종목 — 재주문 방지
        return
    if hm > ENTRY_END:
        _log(f"  ⏰진입마감({ENTRY_END}) — 후보 종료 {code}")
        _trade(code, "후보스킵", px, 0, f"진입마감{ENTRY_END}")
        fl.state = "CONSUMED"
        return
    if int(s.get("fail", 0)) >= 2:
        _log(f"  🚫매수실패 2회 — 후보 종료 {code}")
        _trade(code, "후보스킵", px, 0, "매수실패2회")
        fl.state = "CONSUMED"
        return
    if not _gate_ok(code, px):
        _log(f"  🚧관문미러 차단(가격/시총) {code} @{px:,.0f} — 후보 종료(주문 시도 안 함)")
        _trade(code, "후보스킵", px, 0, "관문미러(가격/시총)")
        fl.state = "CONSUMED"
        return
    now_t = time.time()
    if now_t - _try_ts.get(code, 0) < 5.0:       # FOLLOW 유지 중 과도 재시도 방지
        return
    _try_ts[code] = now_t
    used = sum(1 for x in L["slots"].values() if x.get("pos") or x.get("pending_buy"))
    if used >= SLOTS:
        _log(f"  🈵슬롯 만석({used}/{SLOTS}) — FOLLOW 유지·재시도 대기 {code}")
        return                                   # FOLLOW 유지 — 슬롯 나면 재시도
    st = br.order(code, QTY, "BUY")
    if st in ("OK", "SHADOW", "TIMEOUT"):
        # TIMEOUT = 접수 불명 — pending으로 넣어 fills 확인/미체결취소 경로가 정리(이중주문 방지)
        L["slots"][code] = {"pending_buy": {"t": time.time(), "since": datetime.now().strftime("%H:%M:%S"),
                                            "px": px},
                            "score": fl.score, "brk": fl.brk_px,
                            "depth": round(getattr(fl, "pb_depth", 0), 2), "fail": int(s.get("fail", 0))}
        if st == "SHADOW":
            L["slots"][code].update({"pos": True, "entry": px, "peak": px, "t_in": time.time(),
                                     "armed": False})
            L["slots"][code].pop("pending_buy", None)
        fl.state = "CONSUMED"                    # ★접수 성공 후에만 후보 소비
        _jsave(LEDGER, L)
        _trade(code, "매수주문", px, QTY, f"재출발(점수{fl.score:.0f}·눌림{getattr(fl,'pb_depth',0):.2f}%)·접수{st}")
    else:
        s["fail"] = int(s.get("fail", 0)) + 1
        L["slots"][code] = s
        _jsave(LEDGER, L)
        _log(f"  ⚠️주문거부({st}) {code} 실패{s['fail']}회 — {'후보 종료' if s['fail'] >= 2 else 'FOLLOW 유지·재시도'}")
        if s["fail"] >= 2:
            _trade(code, "후보스킵", px, 0, f"주문거부{s['fail']}회")
            fl.state = "CONSUMED"


def self_manage(br, L, code, s, px, hm):
    # ---- 매수 체결확인 ----
    pb = s.get("pending_buy")
    if pb:
        q, avg_px = _fills_avg(code, pb["since"], "매수")
        if q >= QTY:
            # ★[지침서3] entry = 실제 평균 체결가(fills). 신호가(pb.px)는 참고 기록만.
            entry_px = avg_px if avg_px > 0 else pb["px"]
            s.pop("pending_buy", None)
            s.update({"pos": True, "qty": q, "entry": entry_px, "signal_px": pb["px"],
                      "peak": max(entry_px, px), "t_in": time.time(), "armed": False})
            _jsave(LEDGER, L)
            _log(f"  ✅체결확인 {code} x{q} 체결가{entry_px:,.0f} (신호가{pb['px']:,.0f})")
            _trade(code, "매수체결", entry_px, q, f"fills평균가(신호가{pb['px']:,.0f})")
        elif time.time() - pb["t"] > FILL_WAIT:
            br.cancel_open(code, buy=True)
            # ★[지침서4] 취소 후 최종 체결분 재확인 — 1주라도 체결됐으면 부분체결로 포지션 등록
            #   (기존: 전량 미달이면 실패 처리 → 부분 체결분이 장부 밖 유령 보유가 되던 구멍).
            #   취소 TR 왕복 사이 막판 체결까지 반영. 그 뒤 지연 체결은 FLAT 안전판 몫(주석 명기).
            q2, avg2 = _fills_avg(code, pb["since"], "매수")
            if q2 >= 1:
                entry_px = avg2 if avg2 > 0 else pb["px"]
                s.pop("pending_buy", None)
                s.update({"pos": True, "qty": q2, "entry": entry_px, "signal_px": pb["px"],
                          "peak": max(entry_px, px), "t_in": time.time(), "armed": False})
                _jsave(LEDGER, L)
                _log(f"  🟡PARTIAL_BUY {code} 주문수량{QTY} 체결수량{q2} 잔량{QTY - q2}(취소) 평균체결가{entry_px:,.0f}")
                _trade(code, "PARTIAL_BUY", entry_px, q2, f"주문{QTY}·체결{q2}·잔량{QTY - q2}취소")
            else:
                s.pop("pending_buy", None)
                s["fail"] = int(s.get("fail", 0)) + 1
                _jsave(LEDGER, L)
                _log(f"  👻체결0 {code} — 취소·실패{s['fail']}회")
                _trade(code, "매수실패", pb["px"], 0, "체결0·취소")
        return
    # ---- 매도 체결확인 ----
    ps = s.get("pending_sell")
    if ps:
        held = int(s.get("qty", QTY))
        q, avg_px = _fills_avg(code, ps["since"], "매도")
        if q >= held:
            # ★[지침서3] 손익 = 실제 평균 매도체결가 기준(주문시점가 아님)
            sell_px = avg_px if avg_px > 0 else ps["px"]
            pnl = round((sell_px / s["entry"] - 1) * 100, 2) if s.get("entry") else ""
            _log(f"  ✅매도체결 {code} x{q} 체결가{sell_px:,.0f} ({ps['why']}) {pnl}%")
            _trade(code, "매도체결", sell_px, q, ps["why"], pnl)
            s.clear(); s["done"] = True
            _jsave(LEDGER, L)
        elif time.time() - ps["t"] > FILL_WAIT:
            br.cancel_open(code, buy=False)
            # ★[지침서4] 취소 후 부분체결 반영 — 장부수량 = 실보유(체결분 차감), 재매도는 잔량만
            #   (기존: 전량 재주문 → 부분체결 시 초과 매도 주문이 나가던 구멍).
            q2, avg2 = _fills_avg(code, ps["since"], "매도")
            remain = held - q2
            if q2 >= 1 and remain > 0:
                sell_px = avg2 if avg2 > 0 else ps["px"]
                pnl = round((sell_px / s["entry"] - 1) * 100, 2) if s.get("entry") else ""
                s["qty"] = remain                      # ★장부 = 실제 보유수량
                _log(f"  🟡PARTIAL_SELL {code} 보유수량{held} 체결수량{q2} 잔량{remain} "
                     f"평균매도가{sell_px:,.0f} 재매도수량{remain}")
                _trade(code, "PARTIAL_SELL", sell_px, q2, f"보유{held}·체결{q2}·잔량{remain}", pnl)
            elif remain <= 0:                          # 취소 직전 막판 전량 체결
                sell_px = avg2 if avg2 > 0 else ps["px"]
                pnl = round((sell_px / s["entry"] - 1) * 100, 2) if s.get("entry") else ""
                _trade(code, "매도체결", sell_px, q2, ps["why"], pnl)
                s.clear(); s["done"] = True
                _jsave(LEDGER, L)
                return
            tries = int(ps.get("tries", 1))
            if tries >= 3:
                _log(f"  🚨매도 3회 실패 {code} 잔량{s.get('qty')} — FLAT 안전판 대기")
                ps["t"] = time.time() + 9999
            else:
                st = br.order(code, int(s.get("qty", QTY)), "SELL")   # ★잔량만 재매도
                ps.update({"t": time.time(), "since": datetime.now().strftime("%H:%M:%S"),
                           "px": px, "tries": tries + 1})
                _log(f"  🔁재매도 {code} x{int(s.get('qty', QTY))} {tries + 1}회차 → {st}")
            _jsave(LEDGER, L)
        return
    # ---- 보유 관리(트레일/손절/시간/장청산) ----
    if not s.get("pos"):
        return
    entry = float(s.get("entry") or 0)
    if entry <= 0:
        return
    s["peak"] = max(float(s.get("peak") or entry), px)
    r = (px / entry - 1) * 100
    if not s.get("armed") and r >= TRAIL_ARM:
        s["armed"] = True
        _log(f"  🎯트레일 무장 {code} +{r:.2f}%")
    why = None
    if hm >= EXIT_HM:
        why = f"장청산{EXIT_HM}"
    elif s.get("armed") and px <= s["peak"] * (1 - TRAIL / 100):
        why = f"트레일(고점-{TRAIL}%)"
    elif not s.get("armed") and r <= STOP:
        why = f"하드손절{STOP}%"
    elif time.time() - float(s.get("t_in") or time.time()) >= HOLD_MAX:
        why = f"{int(HOLD_MAX/60)}분경과"
    if why:
        st = br.order(code, int(s.get("qty", QTY)), "SELL")
        if st in ("OK", "SHADOW"):
            s["pos"] = False
            s["pending_sell"] = {"t": time.time(), "since": datetime.now().strftime("%H:%M:%S"),
                                 "px": px, "why": why, "tries": 1}
            if st == "SHADOW":
                pnl = round(r, 2)
                _trade(code, "매도(그림자)", px, int(s.get("qty", QTY)), why, pnl)
                s.clear(); s["done"] = True
        _jsave(LEDGER, L)
        _trade(code, "매도주문", px, int(s.get("qty", QTY)), why, round(r, 2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
