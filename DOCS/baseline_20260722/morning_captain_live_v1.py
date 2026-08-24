# -*- coding: utf-8 -*-
"""🔥 아침 대장 (Morning Captain) — ★소액 실전  [2026-07-15 신설]

친구님 "내일은 테마대장주만 실전 테스트 할 거야. 소액으로."
친구님 "대장주를 쫓아가면서 눌림 때마다 사고 팔고를 하면서 쫓아가길 원한다."
친구님 "그런데 돈이 통장에 돌아온 순간 다른 데로 사버리면 어떻게 하니. 이게 걱정이야."

■ ★돈이 새지 않게 하는 잠금
  1겹  ONLY_MF_ALLOW=MFLOWCAP  → 주문 최후 관문이 rqname 접두어로 거른다.
       깊은바닥(MFLOW_BUY_…)·종가매수(EODGAP)는 **매수 주문 자체가 거부**된다.
       (매도는 이 관문을 안 타므로 기존 포지션 정리는 정상)
  ★[2026-07-17 친구님 "최대 3종목 삭제 — 조건되면 매수하는쪽으로, 돈은 로테이션·전략 우선순위로 사용"]
       종목고정 잠금 삭제. 슬롯 수 한도는 공용 풀(SHARED_MAX_SLOTS)만 남는다.
       A를 팔아 슬롯이 비면 → 그 시점 아직 안 산 대장 후보 중 순위(시가대비 상승률)가
       가장 높은 종목을 그 즉시 매수한다(같은 종목 재매수 ③과는 별개 경로).
       대장 후보 수 자체도 상한 없음(선별판 쪽 CAP_SLOTS 삭제) — 조건①~⑥ 통과하는 만큼 전부 순위표에 오른다.

■ 진입 (선별기 money_flow_board_v1 이 발행한 captain 신호 그대로 — 조건 추가 안 함)
  09:03 판정 · 시가대비 3%↑ · 고가갱신율 35%↑ · 양봉비율 60%↑
  · ★[7/16 친구님 최종·A/B 백테 확정] 전일 거래대금 700억~2조 + 주가 1만원↑ + 분당 1억 안전핀
    (246일: 전일 700억 +1.53%/하루 +47,140원 > 당일 30억안 +1.02% — 데이터가 친구님 원안 승.
     시총·당일 누적대금 관문 폐지 · captain_gate_ab_v51 참조)
  정렬 = 시가 대비 상승률 순 → 상위 MC_SLOTS(3)

■ 매도·재매수 (2026-07-15 백테 확정 · captain_causal_v37 / v38)
  ① -3% 가차없이 손절 (진입가 대비 · 유예 없음)
  ② ★고점 대비 -0.5% → 즉시 전량매도   (봉을 안 기다린다. 1분봉 신호는 늘 늦다)
  ③ ★저점 대비 +0.3% → 즉시 재매수     (최대 5회 · 현재 MC_MAX_RE=0으로 꺼둔 상태)
  ④ ★[2026-07-17] 진입창(ENTRY_HM~ENTRY_END, 09:00~09:20)과 매도마감(EXIT_HM, 09:40)은 분리.
    09:20 이후로는 새 진입(로테이션 포함) 없이 보유분만 계속 관리 — 09:20 무조건청산은 삭제,
    09:40 그 시각까지도 안 팔렸을 때만 그제서야 무조건 전량청산.
  ⑤ ★[2026-07-17 친구님 "5일선 이탈+매수세 꺼지면 매도 맞아, 10일선은 보험이야"] 두 개는 별도 조건 —
    5일선 아래 ∧ 체결강도<MC_D5_CHE 면 그 자체로 매도(10일선 무관). 이 규칙이 못 잡았을 때(체결강도가
    안 꺼진 채 직선폭포)의 뒤늦은 보험으로, 10일선이 깨지면 그것만으로도 매도.
  ⚠️봉 신호(음봉2연속+위꼬리)는 안 쓴다 — 퍼센트 문턱이 항상 먼저 뜬다(백테 발동 0회).

■ ★8초 지연 실측 (오늘 밤 논쟁의 마지막 미지수)
  주문마다 [이론 트리거가] vs [실제 지시 시점 현재가] 를 같이 남긴다.
  그 차이(%)가 곧 '지연 벌점'이다. 백테 손익분기 = 0.4%.
    지연 < 0.4% → 스윙이 홀딩을 이긴다 (하루 74,000~79,000원 · 홀딩 46,701원)
    지연 > 0.4% → 스윙이 진다 → 즉시 홀딩(09:20 청산)으로 롤백
  → LOG/captain_lag.csv

■ 스위치
  MC_LIVE=YES        실주문 (기본 NO = 그림자)
  MC_CAP             종목당 금액 (기본 SAFEPLUS_CAP_KRW = 30만원)
  MC_SLOTS=3         종목 수
  MC_SELL_PB=0.5     고점 대비 매도 문턱(%)
  MC_BUY_UP=0.3      저점 대비 재매수 문턱(%)
  MC_STOP=-3         가차없이 손절(%) — 운영값(246일 백테 확정·cmd와 일치)
  MC_MAX_RE=5        재매수 최대 횟수
  MC_EXIT=0920       전량청산
  즉시 정지 → config\manual_buy_block.flag  (매수 전면 차단) 또는 setx MC_LIVE NO

■ ★[7/16 친구님 5일선 매도 재정의 — 1초 매도 수술]
  "5일선 이탈하면 매도. 단 올라갈 때 5일선 횡보하며 매수세가 받쳐주면 계속 끌고 간다.
   10일선이 강하게 받쳐주면 5일선 잠시 이탈해도 매도하지 않아."
  → 매도 발동 = 5일선 아래 ∧ 체결강도 < MC_D5_CHE(100·매수세 꺼짐) ∧ 10일선도 깨짐.
    (7/16 1초매도 5건 = 5일선 아래 '상태'로 진입 즉시 매도 — 전부 매수세 120~220으로 쌩쌩했음)
    손절 -4%·꼭지(양봉→음봉∧체결강도<100)·09:20 청산은 그대로. crash/classic 두 매도모드 모두 적용.

■ ★[7/16 수술③ 유령왕복 방지] 접수OK ≠ 체결
  7/16 기가레인: 매수 접수 OK → 체결 0(계좌 무거래)인데 장부는 보유→매도 +1.12% 유령 기록.
  → LIVE 매수는 pending_buy로 적고, 게이트웨이 fills CSV(체결 콜백 직기록)에서 체결확인 후에만 pos=True.
    MC_FILL_WAIT(8초)까지 체결 0이면 미체결 잔량 취소(opt10075→취소) 후 유령 판정:
    최초진입 = 슬롯 회수·장부 삭제(재시도 창 안이면 재도전) / 재매수 = 현금 복귀(re 미증가).
    부분체결 = 잔량 취소·체결분만 장부(매도 초과주문 방지). 확인 전엔 매도/재매수 안 함.
"""
import os, sys, csv, json, time, uuid
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\stock_bot\RUN")
import shared_slots as shared      # [7/16] 공통 슬롯 장부(급락주와 총 200만·6슬롯 공유)

# 경로 — MC_BOARD / MC_SNAP / MC_LEDGER 는 **장외 리허설 전용** 주입구(실전은 기본값 그대로)
BOARD  = Path(os.environ.get("MC_BOARD") or r"C:\stock_bot\data\돈흐름_선별판.json")
SNAP   = Path(os.environ.get("MC_SNAP") or r"C:\stock_bot\IPC\live_micro_snapshot.json")
BARS1M = Path(r"C:\stock_bot\data\돈맥_1분봉.json")            # [7/15 급락주 매도 이식] 양봉→음봉·5분선
CHE    = Path(r"C:\stock_bot\data\돈흐름_che_state.json")      # 체결강도
EOD    = Path(r"C:\stock_bot\data\eod_daily_bars.csv")         # 일봉 5일선
NAMEC  = Path(r"C:\stock_bot\data\_code_name_cache.json")
LEDGER = Path(os.environ.get("MC_LEDGER") or r"C:\stock_bot\data\captain_live_ledger.json")
LAGCSV = Path(os.environ.get("MC_LAGCSV") or r"C:\stock_bot\LOG\captain_lag.csv")
# ★[2026-07-20 친구님 승인 ㉮] 지시가→실체결가 괴리 실측 — captain_lag.csv(이론가→지시가)의 사각 보완.
#   (7/20 테스 매도 지시 201,500 → 실체결 199,700(-0.89%)이 어디에도 안 잡히던 것)
SLIPCSV = Path(os.environ.get("MC_SLIPCSV") or r"C:\stock_bot\LOG\captain_slip.csv")
LOG    = Path(r"C:\stock_bot\data\LOG\morning_captain_live.log")

LIVE      = os.environ.get("MC_LIVE", "NO").strip().upper() == "YES"
CAP       = float(os.environ.get("MC_CAP") or os.environ.get("SAFEPLUS_CAP_KRW", "300000"))
# ★[2026-07-19 친구님 지시 "캡틴도 1주씩"] >0이면 종목당 고정 주수 매수(금액 무시)·0=CAP 금액 방식.
QTY_FIX   = int(os.environ.get("MC_QTY_FIX", "0"))
SLOTS     = int(os.environ.get("MC_SLOTS", "3"))
SELL_PB   = float(os.environ.get("MC_SELL_PB", "0.5"))    # 고점 대비 -0.5% (classic 모드)
# ★[7/15 친구님 "급락주 매도 방법을 아침대장에 이식·매도 통일"] 매도 방식 스위치
#   crash  = 급락주식: 양봉→음봉(완성봉)∧체결강도<SELL_CHE  또는  DEFENSE(일봉5일선/1분봉5분선) 이탈
#   classic= 기존: 고점 대비 -SELL_PB%   ← 롤백: setx MC_SELL_MODE classic
SELL_MODE = os.environ.get("MC_SELL_MODE", "classic").strip().lower()   # ★[7/19] 기본값=운영값 정렬(7/16 기가레인 사고로 classic 확정)
SELL_CHE  = float(os.environ.get("MC_SELL_CHE", "100"))   # 매도(음봉) 체결강도 문턱
DEFENSE   = os.environ.get("MC_DEFENSE", "d5").strip().lower()   # d5=일봉5일선 / ma5=1분봉5분선
# ★[7/16 친구님 "5일선 이탈하면 매도. 단 올라갈 때 5일선 횡보하며 매수세가 받쳐주면 계속 끌고 간다.
#   10일선이 강하게 받쳐주면 5일선 잠시 이탈해도 매도하지 않아"]
#   5일선 아래 '상태'만으로 즉시 매도하던 것(7/16 1초매도 5건 원인 — 전부 매수세 120~220으로 쌩쌩했음) 금지.
#   매도 발동 = 5일선 아래 ∧ 체결강도 < D5_CHE(매수세 꺼짐) ∧ 10일선도 깨짐(10일선 위면 잠시 이탈 = 홀딩).
D5_CHE    = float(os.environ.get("MC_D5_CHE", "100"))     # 5일선 이탈 매도의 매수세 문턱
# ★[7/15 친구님 "재매수=눌림을 급락주 바닥패턴으로"] crash모드 재매수에 체결강도 게이트(급락주 진입과 동일)
BUY_CHE   = float(os.environ.get("MC_BUY_CHE", "105"))    # 재매수(눌림 바닥) 체결강도 문턱
BUY_UP    = float(os.environ.get("MC_BUY_UP", "0.3"))     # 저점 대비 +0.3%
STOP      = float(os.environ.get("MC_STOP", "-3"))        # 가차없이 손절 ★[7/19] 기본값=운영값(-3·246일 백테 확정) 정렬
TRAIL2    = float(os.environ.get("MC_TRAIL2", "-2"))      # ★[7/16 친구님] 고점 대비 -2% 보험매도(-0.5%가 못 팔았을 때 2차 안전망·0이면 끔)
MAX_RE    = int(os.environ.get("MC_MAX_RE", "5"))
# ★[7/16 수술③ 유령왕복] 접수OK ≠ 체결(broker_client 계약: 실체결은 Chejan 별도) — 기가레인이 접수만 되고
#   체결 0인데 +1.12% 유령 왕복 기록. 매수 후 FILL_WAIT초 안에 게이트웨이 fills CSV에서 체결확인 못 하면
#   미체결 잔량 취소 → 유령 판정(장부 미기록·슬롯 반환). 확인 전엔 보유도 현금도 아님(매도/재매수 금지).
FILL_WAIT = float(os.environ.get("MC_FILL_WAIT", "8"))
# ★[2026-07-20 친구님 승인 ㉯] 유령 재시도 추격 상한(%) — 당일 최초 시도가 대비 이만큼 위에서는 재도전 금지.
#   (7/20 기가레인: 신호 12,380 → 유령 5회 끝에 12,800(+3.4%) 추격 체결 — 장부 +1.03%·실체결 -80원)
#   가격이 상한 안으로 돌아오면 다시 매수 가능(검사는 매 루프·로그 1회). 0이면 끔.
CHASE_MAX = float(os.environ.get("MC_CHASE_MAX", "2.0"))
ENTRY_HM  = os.environ.get("MC_ENTRY", "0900")            # ★[7/19] 기본값=운영값 정렬(7/17 확정 09:00~09:20 진입)
ENTRY_END = os.environ.get("MC_ENTRY_END", "0920")
EXIT_HM   = os.environ.get("MC_EXIT", "0940")             # ★[7/19] 09:20=신규진입 종료일 뿐 — 청산은 09:40(7/17 확정)
END_HM    = os.environ.get("MC_END", "0942")
# ★[2026-07-19 지침6 — 무위험 배선] 선별판 신선도 관문 — 낡으면 신규매수만 금지(보유 매도는 계속)
BOARD_STALE_SEC = float(os.environ.get("MC_BOARD_STALE_SEC", "180"))


def _board_fresh(board, now=None):
    """선별판 신선도 — (ok, 사유). ts가 오늘 날짜 + 나이 ≤ BOARD_STALE_SEC일 때만 신규매수 허용.
    월요일 09:00 보드 첫 기록 전(금요일 잔존 선별판)·장중 보드 사망 시 낡은 대장 매수를 차단한다."""
    now = now or datetime.now()
    ts = str((board or {}).get("ts") or "")
    if not ts:
        return False, "BOARD_MISSING(ts없음)"
    if ts[:10] != now.strftime("%Y-%m-%d"):
        return False, f"BOARD_STALE(날짜 {ts[:10]})"
    try:
        age = (now - datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        return False, "BOARD_STALE(ts해석불가)"
    if age > BOARD_STALE_SEC:
        return False, f"BOARD_STALE(age {age:.0f}s)"
    return True, "OK"
LOOP_SEC  = float(os.environ.get("MC_LOOP_SEC", "2"))     # ★8초가 아니라 2초 — 지연을 줄인다
RUN_SEC   = float(os.environ.get("MC_RUN_SEC", "55"))     # 태스크 1분 재기동 패턴

LAG_COLS = ["일자", "시각", "종목코드", "종목명", "방향", "사유",
            "고점", "저점", "★이론트리거가", "★지시시점현재가", "★지연퍼센트",
            "수량", "진입가", "수익퍼센트", "재매수회차", "주문결과"]


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


def _cur(code):
    try:
        snap = json.loads(SNAP.read_text(encoding="utf-8-sig"))
        v = snap.get("codes", {}).get(str(code).zfill(6)) or {}
        # ★[7/16 수술] 브로커 재기동 후 스냅샷에 어제 시세가 잔존 — ts가 있고 오늘이 아니면 무시(ts 없으면 기존대로 신뢰)
        ts = str(v.get("ts") or "")
        if ts and ts[:10] != datetime.now().strftime("%Y-%m-%d"):
            return 0.0
        return float(v.get("cur", 0) or 0)
    except Exception:
        return 0.0


# ── [7/15 급락주 매도 이식] 체결강도·1분봉·양봉→음봉·5일선 (crash_flow_live에서) ──
def _che(code):
    try:
        d = json.loads(CHE.read_text(encoding="utf-8-sig"))
        v = d.get(str(code).zfill(6))
        if isinstance(v, dict):
            return float(v.get("last", 0) or 0)
    except Exception:
        pass
    return 0.0


def _bar1m(code):
    """이번 분 1분봉 {o,h,l,c,pos,bull,prev[[o,h,l,c]..]} — 낡았으면 None."""
    try:
        d = json.loads(BARS1M.read_text(encoding="utf-8-sig"))
        if str(d.get("hm", "")) != datetime.now().strftime("%H%M"):
            return None
        return (d.get("m") or {}).get(str(code).zfill(6))
    except Exception:
        return None


def _flip_bear(b):
    """양봉→음봉 완성봉 전환 = 직전 두 완성봉이 [양봉, 음봉]. 미완성 봉으로 판정 안 함."""
    if not b:
        return False
    prev = b.get("prev") or []
    if len(prev) < 2:
        return False
    try:
        a_o, a_h, a_l, a_c = [float(x) for x in prev[-2][:4]]
        z_o, z_h, z_l, z_c = [float(x) for x in prev[-1][:4]]
        return a_c > a_o and z_c < z_o
    except Exception:
        return False


def _ma5_1m(b):
    if not b:
        return None
    prev = b.get("prev") or []
    if len(prev) < 5:
        return None
    try:
        return sum(float(x[3]) for x in prev[-5:]) / 5.0
    except Exception:
        return None


def _ma_daily(*ns):
    """{n: {code: 일봉 n일선}} — 직전 n거래일 종가평균. ★[7/16 친구님 10일선 지지] 한 번 파싱으로 여러 선."""
    import collections
    raw = collections.defaultdict(dict)
    try:
        with EOD.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                raw[r["code"].zfill(6)][r["date"]] = float(r.get("close") or 0)
    except Exception:
        return {n: {} for n in ns}
    out = {n: {} for n in ns}
    for c, byd in raw.items():
        ks_all = sorted(byd)
        for n in ns:
            ks = ks_all[-n:]
            if ks:
                out[n][c] = sum(byd[d] for d in ks) / len(ks)
    return out


_FILLS_DIR = Path(os.environ.get("MC_FILLS_DIR") or r"C:\stock_bot\LOG")   # [지침서5] 리허설 주입구


def _fills_qty(code, since_hms, side="매수"):
    """★[7/16 수술③·㉮] 체결확인 그라운드트루스 — 게이트웨이가 체결 콜백(Chejan)에서 직접 쓰는
       LOG\\fills_YYYYMMDD.csv에서 since 이후 이 종목 해당 방향('매수'/'매도') 체결의 주문번호별 누적체결량 합.
       (fill_qty=FID911은 주문별 누적치 → 주문번호별 max. 접수OK여도 여기 없으면 체결 0 = 유령)
       ★[지침서5] 이제 '표시/폴백'용 — 실제 확정은 주문번호 단위 _fills_onos 사용."""
    fp = _FILLS_DIR / f"fills_{datetime.now():%Y%m%d}.csv"
    if not fp.exists():
        return 0
    code = str(code).zfill(6)
    best = {}
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
                    ono = str(r.get("order_no", "")).strip() or f"?{ts}"
                    if q > best.get(ono, 0):
                        best[ono] = q
                except Exception:
                    continue
    except Exception:
        return 0
    return sum(best.values())


def _fills_onos(code, side="매수", since_hms="00:00:00"):
    """★[지침서5] fills CSV를 '주문번호별' {ono: (누적체결량, 가중평균체결가)}로 집계.
       fill_qty=주문별 누적치 → 행 간 증가분×fill_px 가중. 다른 엔진 주문(다른 번호)과 절대 안 섞임."""
    fp = _FILLS_DIR / f"fills_{datetime.now():%Y%m%d}.csv"
    if not fp.exists():
        return {}
    code = str(code).zfill(6)
    prev, out = {}, {}
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
                    ono = str(r.get("order_no", "")).strip()
                    if not ono:
                        continue
                    q = int(float(r.get("fill_qty") or 0))
                    px = float(r.get("fill_px") or 0)
                    inc = q - prev.get(ono, 0)
                    if inc > 0:
                        prev[ono] = q
                        tq, wsum = out.get(ono, (0, 0.0))
                        out[ono] = (tq + inc, wsum + inc * px)
                except Exception:
                    continue
    except Exception:
        return {}
    return {o: (q, (w / q if q > 0 else 0.0)) for o, (q, w) in out.items()}


def _ono_discover(pend, code, side):
    """★[지침서5] 내 주문번호 확정 — 발주 직전 스냅샷(known)에 없던 '신규' 번호를 fills에서 찾는다.
       정확히 1개면 확정(ORDER_NO 로그). 2개↑면 모호(다른 엔진 동시주문) — 경고 후 대기(합산 금지)."""
    if pend.get("ono"):
        return pend["ono"]
    known = set(pend.get("known") or [])
    news = [o for o in _fills_onos(code, side, str(pend.get("since") or "00:00:00")) if o not in known]
    if len(news) == 1:
        pend["ono"] = news[0]
        _log(f"  🔖ORDER_NO {code} {side} 주문번호={news[0]} 확정")
        return news[0]
    if len(news) > 1 and not pend.get("_ambig"):
        pend["_ambig"] = 1
        _log(f"  ⚠️주문번호 모호 {code} {side} 신규 {len(news)}개({','.join(news)}) — 동시주문 의심·확정 대기(합산 금지)")
    return ""


def _known_onos(br, code, side):
    """발주 직전 스냅샷 — 이 종목의 기존 주문번호 전부(fills 체결분 + 미체결 잔량)."""
    ks = set(_fills_onos(code, side, "00:00:00").keys())
    try:
        ks |= set((br.open_onos(code, buy=(side == "매수")) or {}).keys())
    except Exception:
        pass
    return sorted(ks)


def _lag_row(r):
    try:
        LAGCSV.parent.mkdir(parents=True, exist_ok=True)
        new = not LAGCSV.exists()
        with LAGCSV.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LAG_COLS, extrasaction="ignore", restval="")
            if new:
                w.writeheader()
            w.writerow(r)
    except Exception as e:
        _log(f"지연기록 실패: {e}")


SLIP_COLS = ["일자", "시각", "종목코드", "종목명", "방향", "지시가", "실체결가", "괴리퍼센트"]


def _slip_row(code, nm, side, px, fill):
    """★[2026-07-20 친구님 승인 ㉮] 지시가 vs 실체결가 괴리 — 체결확인 시점에 기록.
       매수 +면 비싸게 샀고 매도 -면 싸게 팔린 것(둘 다 손해 방향). 기록 실패해도 매매는 계속(fail-open)."""
    try:
        SLIPCSV.parent.mkdir(parents=True, exist_ok=True)
        new = not SLIPCSV.exists()
        with SLIPCSV.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SLIP_COLS)
            if new:
                w.writeheader()
            w.writerow({"일자": datetime.now().strftime("%Y%m%d"), "시각": datetime.now().strftime("%H:%M:%S"),
                        "종목코드": code, "종목명": nm, "방향": side,
                        "지시가": round(px), "실체결가": round(fill, 1),
                        "괴리퍼센트": round((fill / px - 1) * 100, 3) if px else ""})
    except Exception as e:
        _log(f"슬리피지기록 실패: {e}")


class Broker:
    def __init__(self):
        self.bc = None
        self.acc = ""

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
            if not self.acc:
                _log("🚨 계좌 없음"); return False
            return True
        except Exception as e:
            _log(f"🚨 브로커 연결 실패: {e}")
            return False

    def order(self, code, qty, side):
        """side: BUY / SELL   ·  ★rqname = MFLOWCAP_… (격리 관문 통과 + 깊은바닥과 분리)"""
        if not LIVE:
            _log(f"  [그림자] {side} {code} x{qty}")
            return "SHADOW"
        try:
            r = self.bc.send_order_real(
                idempotency_key=f"mflowcap_{side.lower()}_{code}_{uuid.uuid4()}",
                account=self.acc, code=code, qty=int(qty),
                order_type=(1 if side == "BUY" else 2), price=0,
                hoga_gb="06", rqname=f"MFLOWCAP_{side}_{code}", screen_no="9746")
            st = str((r or {}).get("status", "")).upper()
            ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
            _log(f"  [{'LIVE' if LIVE else '그림자'}] {side} {code} x{qty} → {st} "
                 f"{'성공' if ok else '★실패'}")
            return st or "NONE"
        except Exception as e:
            _log(f"  🚨 주문 실패 {side} {code}: {e}")
            return "ERROR"

    def cancel_open_buys(self, code):
        """★[7/16 수술③] 이 종목의 미체결 매수주문 전량취소(opt10075 조회 → order_type 3).
           체결0 판정 후 재시도 전에 잔량을 죽여 이중매수를 막는다. 실패해도 fail-open(로그만) —
           만에 하나 취소 실패 후 뒤늦게 체결된 잔량은 FLAT 09:24 안전판이 청산."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1", "매매구분": "2",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"MFLOWCAP_OPEN_{code}", screen_no="9747", timeout_sec=6.0)
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
                    idempotency_key=f"mflowcap_cxl_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=3, price=0, hoga_gb="00",
                    rqname=f"MFLOWCAP_CXL_{code}", screen_no="9747",
                    origin_order_no=ono)
                _log(f"  🧹매수잔량 취소 {code} 주문{ono} x{rem} → "
                     f"{str((cr or {}).get('status', '')).upper()}")
            except Exception as e:
                _log(f"  ⚠️취소 실패 {code}: {e}")

    def cancel_open_sells(self, code):
        """★[7/16 친구님 승인 ㉮] 이 종목의 미체결 매도주문 전량취소(opt10075 매매구분1 → order_type 4).
           매도 체결0 판정 후 재매도 전에 잔량을 죽여 이중매도를 막는다. fail-open(로그만)."""
        if not LIVE or not self.bc:
            return
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1", "매매구분": "1",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"MFLOWCAP_OPENS_{code}", screen_no="9747", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 매도 조회 실패 {code}: {e}")
            return
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if not ono or rem <= 0:
                    continue
                cr = self.bc.send_order_real(
                    idempotency_key=f"mflowcap_cxls_{code}_{uuid.uuid4()}",
                    account=self.acc, code=str(code).zfill(6), qty=rem,
                    order_type=4, price=0, hoga_gb="00",
                    rqname=f"MFLOWCAP_CXLS_{code}", screen_no="9747",
                    origin_order_no=ono)
                _log(f"  🧹매도잔량 취소 {code} 주문{ono} x{rem} → "
                     f"{str((cr or {}).get('status', '')).upper()}")
            except Exception as e:
                _log(f"  ⚠️매도취소 실패 {code}: {e}")

    # ---- ★[지침서5] 주문번호 단위 조회·지정취소 (다른 엔진 주문은 절대 안 건드림) ----
    def open_onos(self, code, buy=True):
        """이 종목의 미체결 {주문번호: 미체결수량} (opt10075). 실패 시 None(판단불가·fail-open)."""
        if not LIVE or not self.bc:
            return {}
        try:
            r = self.bc.tr("opt10075",
                           inputs={"계좌번호": self.acc, "전체종목구분": "1",
                                   "매매구분": "2" if buy else "1",
                                   "종목코드": str(code).zfill(6), "체결구분": "1"},
                           output_fields=["주문번호", "종목코드", "주문구분", "주문수량",
                                          "미체결수량", "주문상태"],
                           rqname=f"MFLOWCAP_ONO_{code}", screen_no="9747", timeout_sec=6.0)
            recs = ((r or {}).get("data") or {}).get("records") or []
        except Exception as e:
            _log(f"  ⚠️미체결 조회 실패 {code}: {e}")
            return None
        out = {}
        for x in recs:
            try:
                ono = str(x.get("주문번호", "")).strip()
                rem = int(float(str(x.get("미체결수량") or "0").replace(",", "") or 0))
                if ono and rem > 0:
                    out[ono] = rem
            except Exception:
                continue
        return out

    def cancel_order(self, code, ono, rem, buy=True):
        """★[지침서5] 내 주문번호만 지정 취소(CANCEL_REQUEST). 종목단위 전량취소는 번호 미확정 폴백 전용."""
        if not LIVE or not self.bc or not ono:
            _log(f"  📨CANCEL_REQUEST {code} 주문번호={ono or '?'} x{rem} (그림자/번호없음 — 실취소 생략)")
            return "SKIP"
        try:
            cr = self.bc.send_order_real(
                idempotency_key=f"mflowcap_cxlono_{code}_{uuid.uuid4()}",
                account=self.acc, code=str(code).zfill(6), qty=int(rem),
                order_type=(3 if buy else 4), price=0, hoga_gb="00",
                rqname=f"MFLOWCAP_CXL_{code}", screen_no="9747", origin_order_no=str(ono))
            st = str((cr or {}).get("status", "")).upper()
            _log(f"  📨CANCEL_REQUEST {code} 주문번호={ono} x{rem} → {st}")
            return st
        except Exception as e:
            _log(f"  ⚠️지정취소 실패 {code} 주문번호={ono}: {e}")
            return "ERROR"


def _pend_buy_step(br, L, code, s, hm, shared, today):
    """★[지침서5] 매수 대기 1스텝(본루프에서 추출 — 동작 동일+주문번호화). 반환=dirty.
       흐름: 주문번호 확정(ORDER_NO) → 전량체결 즉시확정 / 부분·시간초과 → CANCEL_REQUEST →
       CANCEL_CONFIRMED(미체결조회에서 소멸 확인) → FINAL_FILL_QTY·FINAL_AVG_PRICE → 장부 반영."""
    pb = s["pending_buy"]
    nm = s.get("name") or code
    ono = _ono_discover(pb, code, "매수")
    fills = _fills_onos(code, "매수", str(pb.get("since") or "00:00:00"))
    filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
    need = int(pb["qty"])

    def _register(fq, fa):
        s["pos"] = True
        s["qty"] = int(min(fq, need))
        s["entry"] = float(pb["px"])       # ★전략 불변 — 매도 트리거 기준가(신호가) 유지
        s["fill_avg"] = round(fa, 1)        # 실평균체결가는 참고 필드(지침서5 §5)
        s["peak"] = float(pb["px"])
        s["low"] = 0.0
        if int(pb.get("re") or 0):
            s["re"] = int(pb["re"])
        s.pop("pending_buy", None)
        if fa > 0 and float(pb.get("px") or 0) > 0:
            _slip_row(code, nm, "매수", float(pb["px"]), fa)   # ★[7/20 ㉮] 지시가→실체결가 괴리 실측

    # ── 취소 진행 중: 취소 완료 확인 후에만 최종 확정(지침서5 §3) ──
    if pb.get("cxl_t"):
        if time.time() - float(pb.get("cxl_chk") or 0) < 2.0:
            return False
        pb["cxl_chk"] = time.time()
        op = br.open_onos(code, buy=True)
        confirmed = (op is not None) and ((ono and ono not in op) or (not ono and not op))
        timed_out = time.time() - float(pb["cxl_t"]) >= 10.0
        if not (confirmed or timed_out):
            return False
        if confirmed:
            _log(f"  ✅CANCEL_CONFIRMED {nm}({code}) 주문번호={ono or '?'}")
        else:
            _log(f"  ⚠️취소확인 시간초과 {nm}({code}) 주문번호={ono or '?'} — 최종수량으로 진행")
        fills = _fills_onos(code, "매수", str(pb.get("since") or "00:00:00"))
        filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono or '?'} {filled}/{need}주 · "
             f"FINAL_AVG_PRICE {favg:,.0f}")
        if filled >= 1:
            _register(filled, favg)
            _log(f"  ✅체결확인 {nm} {filled}/{need}주"
                 + ("" if filled >= need else " ★부분체결 — 취소완료 확인 후 체결분만 장부"))
        elif int(pb.get("re") or 0):
            s.pop("pending_buy", None)
            _log(f"  👻재매수 체결0 {nm} — 취소완료·현금 복귀(유령 방지)")
        else:
            L["slots"].pop(code, None)
            shared.release(code, today)
            _log(f"  👻최초진입 체결0 {nm} — 취소완료·슬롯 회수(유령 왕복 방지)"
                 + ("·다음 루프 재도전" if hm <= ENTRY_END else ""))
        return True

    # ── 전량 체결 → 즉시 확정(취소 불필요) ──
    if ono and filled >= need:
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono} {filled}/{need}주 · "
             f"FINAL_AVG_PRICE {favg:,.0f}")
        _register(filled, favg)
        _log(f"  ✅체결확인 {nm} {filled}/{need}주")
        return True

    # ── 부분체결 확인 또는 시간초과 → 잔량 취소 요청(확정은 취소완료 후로 미룸) ──
    if (ono and 1 <= filled < need) or \
       (time.time() - float(pb.get("sent") or 0)) >= FILL_WAIT or hm >= EXIT_HM:
        op = None
        if not ono:
            op = br.open_onos(code, buy=True)
            news = [o for o in (op or {}) if o not in set(pb.get("known") or [])]
            if len(news) == 1:
                pb["ono"] = ono = news[0]
                _log(f"  🔖ORDER_NO {code} 매수 주문번호={ono} 확정(미체결조회)")
                filled = _fills_onos(code, "매수", str(pb.get("since") or "00:00:00")).get(ono, (0, 0.0))[0]
        if ono:
            rem = (op or {}).get(ono) or max(1, need - filled)   # 취소수량 = 실제 미체결 잔량 우선
            br.cancel_order(code, ono, rem, buy=True)
        else:
            _log(f"  ⚠️주문번호 미확정 {nm}({code}) — 종목단위 전량취소 폴백(교차취소 가능성 로그)")
            br.cancel_open_buys(code)
        pb["cxl_t"] = time.time()
        pb["cxl_chk"] = 0.0
        return True
    return False


def _pend_sell_step(br, code, s, hm, shared, today):
    """★[지침서5] 매도 대기 1스텝 — 재매도는 CANCEL_CONFIRMED 이후 '잔량만'(§4).
       (잔량 재매도 자체는 기존 보유관리 로직이 s['qty']로 수행 — pending 해제만 여기서)."""
    ps = s["pending_sell"]
    nm = s.get("name") or code
    need = int(ps.get("qty") or 0)
    ono = _ono_discover(ps, code, "매도")
    fills = _fills_onos(code, "매도", str(ps.get("since") or "00:00:00"))
    filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)

    def _full_done():
        s["realized"] = round(float(s["realized"]) + float(ps["ret"]), 3)
        # ★[2026-07-20 친구님 승인 ㉮] 실체결 기준 손익 병기 — 장부(신호가 기준·전략 불변)와 별도 필드.
        #   (7/20 장부 +8,838원 주장 vs 실체결 -3,230원 괴리를 매일 자동으로 드러낸다)
        rr = None
        fe = float(s.get("fill_avg") or 0)
        if favg > 0 and fe > 0:
            rr = (favg / fe - 1) * 100
            s["real_realized"] = round(float(s.get("real_realized") or 0) + rr, 3)
            s["real_won"] = round(float(s.get("real_won") or 0) + (favg - fe) * filled, 1)
        if favg > 0 and float(ps.get("px") or 0) > 0:
            _slip_row(code, nm, "매도", float(ps["px"]), favg)
        s["pos"] = False
        s["low"] = float(ps["px"])
        s["qty"] = 0
        s.pop("pending_sell", None)
        _log(f"  ✅매도 체결확인 {nm} {filled}/{need}주 ({float(ps['ret']):+.2f}%) "
             f"누적{s['realized']:+.2f}%"
             + (f" ★실체결 {rr:+.2f}%" if rr is not None else ""))
        if ps.get("why") == "시간청산" or s["re"] >= MAX_RE or hm >= EXIT_HM:
            s["done"] = True
            shared.release(code, today)

    if ps.get("cxl_t"):
        if time.time() - float(ps.get("cxl_chk") or 0) < 2.0:
            return False
        ps["cxl_chk"] = time.time()
        op = br.open_onos(code, buy=False)
        confirmed = (op is not None) and ((ono and ono not in op) or (not ono and not op))
        timed_out = time.time() - float(ps["cxl_t"]) >= 10.0
        if not (confirmed or timed_out):
            return False
        if confirmed:
            _log(f"  ✅CANCEL_CONFIRMED {nm}({code}) 주문번호={ono or '?'}")
        else:
            _log(f"  ⚠️취소확인 시간초과 {nm}({code}) 주문번호={ono or '?'} — 최종수량으로 진행")
        fills = _fills_onos(code, "매도", str(ps.get("since") or "00:00:00"))
        filled, favg = fills.get(ono, (0, 0.0)) if ono else (0, 0.0)
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono or '?'} {filled}/{need}주 · "
             f"FINAL_AVG_PRICE {favg:,.0f}")
        if need > 0 and filled >= need:
            _full_done()                      # 취소 직전 막판 전량 체결
        elif filled >= 1:
            s["qty"] = max(0, need - filled)  # ★장부 = 실보유. 재매도는 보유관리 로직이 '잔량만' 수행
            s.pop("pending_sell", None)
            _log(f"  ⚠️매도 부분체결 {nm} {filled}/{need}주 → 취소완료 확인 후 잔량 {s['qty']}주 재매도 예정")
        else:
            s.pop("pending_sell", None)
            _log(f"  👻매도 체결0 {nm} — 취소완료·재매도(유령 매도 방지)")
        return True

    if ono and need > 0 and filled >= need:
        _log(f"  🧾FINAL_FILL_QTY {nm}({code}) 주문번호={ono} {filled}/{need}주 · "
             f"FINAL_AVG_PRICE {favg:,.0f}")
        _full_done()
        return True

    if (ono and 1 <= filled < need) or \
       (time.time() - float(ps.get("sent") or 0)) >= FILL_WAIT:
        op = None
        if not ono:
            op = br.open_onos(code, buy=False)
            news = [o for o in (op or {}) if o not in set(ps.get("known") or [])]
            if len(news) == 1:
                ps["ono"] = ono = news[0]
                _log(f"  🔖ORDER_NO {code} 매도 주문번호={ono} 확정(미체결조회)")
                filled = _fills_onos(code, "매도", str(ps.get("since") or "00:00:00")).get(ono, (0, 0.0))[0]
        if ono:
            rem = (op or {}).get(ono) or max(1, need - filled)   # 취소수량 = 실제 미체결 잔량 우선
            br.cancel_order(code, ono, rem, buy=False)
        else:
            _log(f"  ⚠️주문번호 미확정 {nm}({code}) — 종목단위 매도 전량취소 폴백(교차취소 가능성 로그)")
            br.cancel_open_sells(code)
        ps["cxl_t"] = time.time()
        ps["cxl_chk"] = 0.0
        return True
    return False


# ══ [2026-07-21 오사장님 지시 — 선별기+Money Flow 병렬구조] 오늘 만든 micro_rank_board.json의
#   MONEY_START 후보 — 기존 선별판(BOARD/money_flow_board_v1)과 완전 독립 소스. 기본 잠금(OFF) —
#   MC_MFE_ENABLE=YES로만 켜짐. 새 TR·새 실시간등록 없음(읽기전용, 둘 다 이미 계산된 파일만 읽음).
MC_MFE_ENABLE = os.environ.get("MC_MFE_ENABLE", "NO").strip().upper() == "YES"
MC_MFE_BOARD = Path(r"C:\stock_bot\data\micro_rank_board.json")
MC_MFE_POOL = Path(r"C:\stock_bot\data\돈맥_전일상위풀.json")
MC_MFE_MIN_PVAL = float(os.environ.get("MC_MFE_MIN_PVAL", "100"))   # 전일 거래대금 100억(단위=억)
MC_MFE_TOP_N = int(os.environ.get("MC_MFE_TOP_N", "10"))


def _money_start_candidates(today):
    """MONEY_START=True AND 전일거래대금≥100억, money_add_5s 내림차순 TOP N. 읽기전용·새 계산 없음."""
    try:
        board = json.loads(MC_MFE_BOARD.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if str(board.get("date") or "") != today:
        return {}
    try:
        pool = json.loads(MC_MFE_POOL.read_text(encoding="utf-8-sig"))
        pvm = {str(c).zfill(6): float(v) for c, px, v in pool.get("rows", [])}
    except Exception:
        pvm = {}
    cands = []
    for it in (board.get("all_items") or []):
        code = it.get("code")
        if not code or not it.get("money_start"):
            continue
        if pvm.get(str(code).zfill(6), 0.0) < MC_MFE_MIN_PVAL:
            continue
        add = it.get("money_add_5s") or 0
        cands.append((add, code, it.get("name") or ""))
    cands.sort(key=lambda x: -x[0])
    out = {}
    for i, (add, code, name) in enumerate(cands[:MC_MFE_TOP_N], 1):
        out[code] = {"rank": None, "rise": None, "hh": None, "bull": None,
                     "che": None, "val": None, "permin": None, "_mf_rank": i, "_mf_add5s": add}
    return out


# ★[2026-07-21 오사장님 지시 — TRUE_LEADER 우선검토] theme_leader_shadow_v1.py가 이미 계산해둔
#   TRUE_LEADER 종목만 그대로 읽어(새 계산 없음) 후보 정렬 우선순위에만 쓴다. 진입조건(_try_enter)
#   은 절대 안 건드림 — 여러 후보가 경쟁할 때 TRUE_LEADER가 먼저 검토되게 순서만 바꾼다.
TL_JSON = Path(r"C:\stock_bot\data\테마주도주.json")


def _true_leader_info(today):
    """{code: 동반종목수(부하)} — theme_leader_shadow_v1.py가 이미 계산해둔 값 그대로 재사용.
    오사장님 지시 "부하를 끌고 있는 대장을 더 우선" — 정렬 가중치로만 씀(새 계산 없음)."""
    try:
        d = json.loads(TL_JSON.read_text(encoding="utf-8-sig"))
        if str(d.get("date") or "") != today:
            return {}
        return {str(x.get("code")).zfill(6): int(x.get("members") or 0)
                for x in (d.get("true_leaders") or []) if x.get("code")}
    except Exception:
        return {}


# ★[2026-07-21 오사장님 지시 — 기관/외국인/프로그램 우선순위 가중치] 골짜기와 동일한 데이터소스
#   (money_flow_board_v1.py가 이미 계산해둔 data\돈흐름_선별판.json) 읽기전용 재사용. 새 TR 없음.
#   매수를 막지 않음 — 정렬 우선순위에만 가산(사양3 원칙 그대로 유지).
SUPPLY_BOARD = Path(r"C:\stock_bot\data\돈흐름_선별판.json")


def _supply_lookup():
    try:
        d = json.loads(SUPPLY_BOARD.read_text(encoding="utf-8-sig"))
        return {str(r.get("code")).zfill(6): r for r in (d.get("rows") or []) if r.get("code")}
    except Exception:
        return {}


def _supply_score(row):
    if not row:
        return 0
    return sum(1 for k in ("inst", "frgn", "prog") if (row.get(k) or 0) > 0)


def main():
    now = datetime.now()
    hm = now.strftime("%H%M")
    today = now.strftime("%Y%m%d")
    if hm > END_HM:
        return
    if hm < "0900":
        return

    _log("=" * 78)
    _log(f"🔥 아침대장 {'★실전(LIVE)' if LIVE else '그림자(주문0)'} — "
         f"종목당 {CAP:,.0f}원 × {SLOTS}슬롯 · 매도 고점-{SELL_PB}% · 재매수 저점+{BUY_UP}% "
         f"× 최대{MAX_RE}회 · 손절 {STOP}% · {EXIT_HM[:2]}:{EXIT_HM[2:]} 청산")

    br = Broker()
    if not br.connect():
        return

    L = _jload(LEDGER, {})
    if L.get("date") != today:
        L = {"date": today, "slots": {}}
        _jsave(LEDGER, L)

    try:
        namemap = json.loads(NAMEC.read_text(encoding="utf-8")).get("map", {})
    except Exception:
        namemap = {}

    _mad = _ma_daily(5, 10)   # [7/15] 급락주 매도 이식용 → ★[7/16 친구님] classic에도 5일선 이탈 매도 — 항상 계산
    MA5D, MA10D = _mad[5], _mad[10]   # ★[7/16 친구님] 10일선 지지 = 5일선 잠시 이탈 홀딩
    d5_hold_logged = set()            # 홀딩 사유 로그 1회/기동(스팸 방지)
    pre10_logged = set()              # ★[7/20] 매수 전 10일선 검사 — 거부 로그 1회/기동(검사는 매 루프)
    # ★[2026-07-20 친구님 승인 ㉰] 계좌 기존보유 종목 매수 제외 — 7/20 원익IPS: 계좌 기존 1주(평단 130,367)
    #   위에 캡틴이 1주 사고팔아 기존 보유분 평단이 135,484로 오염. reconcile(08:50)의 계좌 진실 스냅샷 사용.
    #   파일 없거나 깨지면 필터 없이 진행(fail-open — 매수 자체를 막는 안전판이 아니라 오염 방지용).
    try:
        _rt = _jload(Path(r"C:\stock_bot\data\rt_open_positions.json"), {}) or {}
        HELD = {str(c).zfill(6) for c, v in _rt.items() if int(float((v or {}).get("qty") or 0)) > 0}
    except Exception:
        HELD = set()
    if HELD:
        _log(f"  🏦계좌 기존보유 매수제외 {len(HELD)}종목: " + ", ".join(sorted(HELD)))
    held_logged = set()               # ACCOUNT_HELD 거부 로그 1회/기동
    chase_logged = set()              # ★[7/20 ㉯] CHASE_CAP 거부 로그 1회/기동(검사는 매 루프)
    _log(f"  매도방식 = {SELL_MODE}" + (f" (양봉→음봉∧체결강도<{SELL_CHE:.0f} / {DEFENSE} 이탈 / 손절{STOP}%)"
         if SELL_MODE == "crash" else f" (고점-{SELL_PB}%)"))

    deadline = time.monotonic() + RUN_SEC
    # ★[2026-07-19 통합지침서 — 선별기 관찰 로그(로직 무변경·기록만)]
    cap_top_prev = None          # 직전 1등 코드
    board_warn_last = None       # 선별판 신선도 경고 — 사유 변경 시 1회만 로그
    cap_top_changes = 0          # 1등 변경 횟수
    cap_prev_set = set()         # 직전 사이클 후보 집합(추가/이탈 감지)
    cap_marks = set()            # 5분 단위 후보수 로그 완료 표시
    CAP_MARKS = {"0900", "0905", "0910", "0915", "0920"}

    # ══ [2026-07-21 오사장님 지시 — 선별기+Money Flow 병렬구조] 후보 1종목 진입판단·주문실행을
    #   공통 함수로 추출(내용 변경 없음 — 원래 while 루프 838~915행 그대로, 제어흐름만 함수화).
    #   기존 선별판 후보 루프와 신규 MONEY_START 후보 루프가 이 함수 하나를 그대로 공유한다.
    #   반환값: "SLOTS_FULL"(공용슬롯 소진 — 호출측 루프 break) / "SKIP"(이 종목만 거부 — 다음 후보로)
    #   / "ORDERED"(주문 접수). 조건·수치·시간창·주문 로직 전부 원문 그대로, 1도 안 바꿨다.
    def _try_enter(code, c):
        nonlocal dirty
        if code in L["slots"]:
            return "SKIP"                              # 이미 시도한 종목(보유중·매도완료 불문) — 로테이션 대상 아님
        if shared.count(today) >= SLOTS:      # [7/16] 공통 슬롯 풀 참(급락주가 이미 씀)
            return "SLOTS_FULL"
        px = _cur(code)
        if px <= 0:
            return "SKIP"
        # ★[2026-07-20 친구님 승인 — 10일선 즉사 방지] 매도 '10일선붕괴(보험)'와 정확히 동일한
        #   조건을 매수 직전 재사용 — 10일선 아래에서 태어난 포지션은 체결확인 직후 첫 루프에
        #   무조건 매도되는 자기모순 거래(7/20 코오롱티슈진 -24.2%·제주반도체 -2.8%, 3초 왕복).
        #   여유폭·틱예측 없음. 10일선 위로 회복하면 다시 매수 가능(검사는 매 루프·로그만 1회).
        if MA10D.get(code, 0) > 0 and px < MA10D[code]:
            if code not in pre10_logged:
                pre10_logged.add(code)
                _nm10 = (namemap.get(code) or "")[:10] or code
                _log(f"  ⛔CAPTAIN_REJECT REASON=PRE_10MA_INSURANCE {_nm10}({code}) "
                     f"현재가{px:,.0f} 10일선{MA10D[code]:,.0f} "
                     f"({(px / MA10D[code] - 1) * 100:+.2f}%)")
            return "SKIP"
        # ★[2026-07-20 친구님 승인 ㉰] 계좌에 이미 있는 종목은 매수 금지 — 평단 오염 방지.
        if code in HELD:
            if code not in held_logged:
                held_logged.add(code)
                _log(f"  ⛔CAPTAIN_REJECT REASON=ACCOUNT_HELD "
                     f"{(namemap.get(code) or code)[:10]}({code}) 계좌 기존보유")
            return "SKIP"
        # ★[2026-07-20 친구님 승인 ㉯] 유령 재시도 추격 상한 — 당일 최초 시도가 대비
        #   +CHASE_MAX% 초과 가격에서는 재도전 금지(상한 안으로 돌아오면 다시 매수 가능).
        first = float(L.setdefault("first_px", {}).get(code) or 0)
        if CHASE_MAX > 0 and first > 0 and px > first * (1 + CHASE_MAX / 100):
            if code not in chase_logged:
                chase_logged.add(code)
                _log(f"  ⛔CAPTAIN_REJECT REASON=CHASE_CAP "
                     f"{(namemap.get(code) or code)[:10]}({code}) "
                     f"현재가{px:,.0f} 최초시도가{first:,.0f} "
                     f"(+{(px / first - 1) * 100:.2f}% > {CHASE_MAX}%)")
            return "SKIP"
        qty = QTY_FIX if QTY_FIX > 0 else int(CAP // px)
        if qty < 1:
            return "SKIP"
        if not shared.acquire(code, "CAPTAIN", today):   # [7/16] 공통 슬롯 확보
            return "SKIP"
        nm = (namemap.get(code) or "")[:10] or code
        _log(f"🔥[{c.get('rank')}등] {nm}({code}) @{px:,.0f} x{qty}주 "
             f"시가대비{float(c.get('rise') or 0):+.2f}% 갱신율{c.get('hh')}% "
             f"양봉{c.get('bull')}% 체결강도{c.get('che')} 대금{c.get('val')}억 분당{c.get('permin')}억")
        L.setdefault("first_px", {}).setdefault(code, px)   # ★[7/20 ㉯] 추격 상한 기준 = 당일 최초 시도가
        kn = _known_onos(br, code, "매수")   # ★[지침서5] 발주 직전 주문번호 스냅샷
        st = br.order(code, qty, "BUY")
        ok = st in ("OK", "TIMEOUT", "SHADOW")
        if not ok:
            # ★[7/16 수술②] 실패는 장부에 기록하지 않는다 — 다음 루프에서 이 종목을 다시 시도.
            shared.release(code, today)      # [7/16] 주문 실패 → 슬롯 반환
            _log(f"  ⚠️{nm}({code}) 매수 {st} → 장부 미기록·다음 루프 재시도")
            return "SKIP"
        # ★[7/16 수술③ 유령왕복] 접수OK ≠ 체결 — LIVE는 pending_buy로 적고 체결확인 후에만
        #   pos=True(기가레인: 접수만 되고 체결 0인데 유령 +1.12% 기록). 그림자는 기존대로 즉시 보유.
        L["slots"][code] = {
            "name": nm, "rank": c.get("rank"), "cap": CAP,
            "qty": qty if st == "SHADOW" else 0,
            "entry": px if st == "SHADOW" else 0.0,
            "peak": px, "low": 0.0, "pos": st == "SHADOW", "re": 0,
            "done": False, "realized": 0.0, "rise": c.get("rise"),
        }
        if st != "SHADOW":
            L["slots"][code]["pending_buy"] = {
                "qty": qty, "px": px, "re": 0, "ono": "", "known": kn,
                "since": (now - timedelta(seconds=2)).strftime("%H:%M:%S"),
                "sent": time.time(),
            }
        _lag_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                  "종목명": nm, "방향": "BUY", "사유": "최초진입",
                  "고점": "", "저점": "", "★이론트리거가": round(px),
                  "★지시시점현재가": round(px), "★지연퍼센트": 0.0,
                  "수량": qty, "진입가": round(px), "수익퍼센트": "",
                  "재매수회차": 0, "주문결과": st})
        dirty = True
        return "ORDERED"


    while time.monotonic() < deadline:
        now = datetime.now()
        hm = now.strftime("%H%M")
        if hm > END_HM:
            break
        dirty = False

        # ══ ① 진입 — 대장 조건 통과 후보를 우선순위(시가대비 상승률)대로, 슬롯이 빌 때마다 계속 채운다 ══
        #   [2026-07-17 친구님 "최대 3종목 삭제 조건이 되면 매수하는쪽으로 — 돈은 로테이션, 조건되면
        #    우선순위로 사용"] 종목고정 1회성 락(entered) 삭제. 이미 시도한 종목(L["slots"] 키)은
        #    다시 안 사고, 아직 안 산 후보 중 순위가 가장 높은 종목을 슬롯이 빌 때마다 매수한다.
        if ENTRY_HM <= hm <= ENTRY_END:
            # ★[2026-07-19 지침6] 선별판 신선도 관문 — 낡은 판(금요일 잔존·보드 사망)으로는 신규매수 금지.
            #   보유 종목 매도(아래 ② 루프)는 이 관문과 무관하게 계속 작동한다.
            board = _jload(BOARD) or {}
            b_ok, b_why = _board_fresh(board)
            if not b_ok:
                if b_why != board_warn_last:
                    board_warn_last = b_why
                    _log(f"  ⛔선별판 신선도 불통과 — 신규매수 금지({b_why})·보유 매도는 계속")
                caps = {}
            else:
                board_warn_last = None
                caps = board.get("captain") or {}
            # ── [2026-07-22 수정] Money Flow는 후보를 추가하지 않고 정렬 우선순위로만 쓴다 ──
            #   기존 선별판 후보(board.captain, rise/hh/bull 등 캡틴 원조건을 이미 통과한 종목)만
            #   실매수 자격을 가진다. MONEY_START 단독 종목은 그 조건들을 거치지 않았으므로(rise/hh/
            #   bull/che 전부 None) caps에 추가하지 않는다 — 이전엔 merged[mcode]=minfo로 그대로
            #   추가돼 캡틴 원조건을 우회하고 있었음.
            mf_codes = set(_money_start_candidates(today)) if MC_MFE_ENABLE else set()
            if caps:
                # ★TRUE_LEADER 우선검토 + 기관/외국인/프로그램 수급 가중치(정렬 우선순위에만 사용,
                #   진입조건 무변경) — MONEY_START 발생 여부 → 부하(동반종목수) 많은 대장 → TRUE_LEADER
                #   여부 → 수급 있는 종목 → 기존 rise순. 매수를 막는 조건 아님(오사장님 지시).
                tl_info = _true_leader_info(today)
                supply_map = _supply_lookup()
                cands = sorted(caps.items(),
                                key=lambda kv: (kv[0] not in mf_codes, kv[0] not in tl_info, -tl_info.get(kv[0], 0),
                                                 -_supply_score(supply_map.get(kv[0])),
                                                 -float(kv[1].get("rise") or 0)))
                # ── ★[2026-07-19 통합지침서] 선별기 관찰 로그 — 5분 단위 후보수·1등 변경·추가/이탈 ──
                if hm in CAP_MARKS and hm not in cap_marks:
                    cap_marks.add(hm)
                    _log(f"📊[{hm[:2]}:{hm[2:]}] 대장후보 {len(cands)}종목: "
                         + ", ".join(f"{(namemap.get(c) or c)[:6]}{float(v.get('rise') or 0):+.1f}%"
                                     for c, v in cands[:5]) + (" ..." if len(cands) > 5 else ""))
                top_now = cands[0][0] if cands else None
                if top_now and top_now != cap_top_prev:
                    if cap_top_prev is not None:
                        cap_top_changes += 1
                        _log(f"👑1등 변경 #{cap_top_changes} [{now:%H:%M:%S}]: "
                             f"{(namemap.get(cap_top_prev) or cap_top_prev)[:8]} → "
                             f"{(namemap.get(top_now) or top_now)[:8]}"
                             f"(시가대비{float(cands[0][1].get('rise') or 0):+.1f}%)")
                    cap_top_prev = top_now
                cur_set = {c for c, _v in cands}
                if cap_prev_set and cur_set != cap_prev_set:
                    add_c = sorted(cur_set - cap_prev_set)
                    del_c = sorted(cap_prev_set - cur_set)
                    if add_c:
                        _log("  ➕후보 추가: " + ", ".join(f"{(namemap.get(c) or c)[:6]}({c})" for c in add_c))
                    if del_c:
                        _log("  ➖후보 이탈: " + ", ".join(f"{(namemap.get(c) or c)[:6]}({c})" for c in del_c))
                cap_prev_set = cur_set
                for code, c in cands:
                    result = _try_enter(code, c)   # ★공통함수(내용 원본 그대로) — 출처(선별판/MONEY_START) 무관 1회만 호출
                    if result == "SLOTS_FULL":
                        break

        # ══ ② 추적 — 매도 / 재매수 / 손절 / 청산 ══
        for code, s in list(L.get("slots", {}).items()):   # ★[7/16 수술③] 유령 슬롯 삭제 가능 → 복사본 순회
            if s.get("done"):
                continue

            # ★[7/16 수술③ 유령왕복] 매수 체결확인 — 확정 전엔 보유도 현금도 아님(매도/재매수 금지).
            #   fills CSV(게이트웨이 체결 콜백 직기록)에 체결이 뜨면 그때 pos=True(체결수량만).
            #   FILL_WAIT초까지 체결 0이면 미체결 잔량 취소 → 유령 판정.
            # ★[지침서5] 주문번호 기반 체결·취소 — 로직은 _pend_buy_step으로 추출(리허설 가능화)
            pb = s.get("pending_buy")
            if pb:
                if _pend_buy_step(br, L, code, s, hm, shared, today):
                    dirty = True
                continue

            # ★[7/16 친구님 승인 ㉮] 매도 체결확인 — 접수OK ≠ 팔림. 체결확인 후에만 '팔림' 기록.
            #   (기가레인 매도 "[800033] 0주" = 접수OK인데 체결0. 체결0이면 잔량 취소 후 재매도 = 유령 매도 방지)
            # ★[지침서5] 주문번호 기반 매도 체결·취소 — 재매도는 CANCEL_CONFIRMED 후 '잔량만'
            ps = s.get("pending_sell")
            if ps:
                if _pend_sell_step(br, code, s, hm, shared, today):
                    dirty = True
                continue

            cur = _cur(code)
            if cur <= 0:
                continue
            nm = s.get("name") or code

            # ── 보유 중 ──
            if s["pos"]:
                ent = float(s["entry"] or 0)
                if ent <= 0:
                    continue
                ret = (cur / ent - 1) * 100
                if cur > s["peak"]:
                    s["peak"] = cur; dirty = True

                why, trig = None, None
                # ④ 09:20 전량청산
                if hm >= EXIT_HM:
                    why, trig = "시간청산", cur
                # ① -3% 가차없이 손절
                elif ret <= STOP:
                    why, trig = "손절", ent * (1 + STOP / 100)
                # ② 꼭지매도 — ★[7/15 급락주 매도 이식] MC_SELL_MODE 스위치
                elif SELL_MODE == "crash":
                    b = _bar1m(code); che = _che(code)
                    # ★[7/16 친구님] 매도 = 5일선 아래 ∧ 매수세 꺼짐(체결강도<D5_CHE) ∧ 10일선도 깨짐.
                    #   매수세가 받쳐주거나 10일선 위면 '잠시 이탈' = 홀딩하고 계속 끌고 간다.
                    d5_break = DEFENSE == "d5" and MA5D.get(code, 0) > 0 and cur < MA5D[code]
                    d5_sup = (che >= D5_CHE) or (MA10D.get(code, 0) > 0 and cur >= MA10D[code])
                    if d5_break and not d5_sup:
                        why, trig = f"일봉5일선이탈(체결강도{che:.0f})", cur
                    elif DEFENSE == "ma5" and (_ma5_1m(b) is not None) and cur < _ma5_1m(b):
                        why, trig = "5분선이탈", cur
                    elif _flip_bear(b) and 0 < che < SELL_CHE:
                        why, trig = f"꼭지(양봉→음봉·체결강도{che:.0f})", cur
                    if d5_break and d5_sup and not why and code not in d5_hold_logged:
                        d5_hold_logged.add(code)
                        _log(f"  🤝5일선 아래지만 홀딩 {nm} @{cur:,.0f} — 체결강도{che:.0f}"
                             + (f"·10일선 지지 {MA10D[code]:,.0f}"
                                if MA10D.get(code, 0) > 0 and cur >= MA10D[code] else ""))
                # ②(classic) ★[7/16 친구님 "아침대장에 넣어·-0.5% 보험용"] 고점-2% 보험 → 5일선 이탈 → 고점-0.5%
                elif TRAIL2 < 0 and s["peak"] > ent and (cur / s["peak"] - 1) * 100 <= TRAIL2:
                    why, trig = f"고점{TRAIL2:.0f}%보험", s["peak"] * (1 + TRAIL2 / 100)
                elif MA5D.get(code, 0) > 0 and cur < MA5D[code] and _che(code) < D5_CHE:
                    # ★[2026-07-17 친구님 "5일선 이탈+매수세 꺼지면 매도 맞아 — 10일선은 보험"]
                    #   10일선은 홀딩 조건이 아니라 이 규칙이 못 잡았을 때만 쓰는 별도 보험(바로 아래).
                    why, trig = f"일봉5일선이탈(체결강도{_che(code):.0f})", cur
                elif MA10D.get(code, 0) > 0 and cur < MA10D[code]:
                    # ★[2026-07-17] 10일선 보험 — 체결강도가 안 꺼져 위 규칙이 못 판 케이스(7/16 기가레인형
                    #   직선폭포·체결강도 100 유지)를 잡는 뒤늦은 방어선. 10일선 자체가 깨지면 무조건 매도.
                    why, trig = "10일선붕괴(보험)", cur
                elif s["peak"] > ent and (cur / s["peak"] - 1) * 100 <= -SELL_PB:
                    why, trig = "꼭지매도(classic)", s["peak"] * (1 - SELL_PB / 100)

                if why:
                    kn = _known_onos(br, code, "매도")   # ★[지침서5] 발주 직전 주문번호 스냅샷
                    st = br.order(code, s["qty"], "SELL")
                    if st not in ("OK", "TIMEOUT", "SHADOW"):
                        # ★[7/16 수술①] 매도 실패는 성공 취급 안 함 — 포지션 유지·다음 루프 재시도.
                        #   (실패를 pos=False로 적으면 장부가 거짓 → FLAT 안전판 전부가 유령잔고를 못 본다)
                        _log(f"  🚨매도 실패 {why} {nm} {st} → 포지션 유지·다음 루프 재시도")
                        dirty = True
                        continue
                    lag = (trig - cur) / trig * 100 if trig else 0.0   # ★+면 이론가보다 싸게 팔림
                    _lag_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                              "종목명": nm, "방향": "SELL", "사유": why,
                              "고점": round(s["peak"]), "저점": "",
                              "★이론트리거가": round(trig), "★지시시점현재가": round(cur),
                              "★지연퍼센트": round(lag, 3), "수량": s["qty"],
                              "진입가": round(ent), "수익퍼센트": round(ret, 2),
                              "재매수회차": s["re"], "주문결과": st})
                    if st == "SHADOW":
                        s["realized"] = round(float(s["realized"]) + ret, 3)
                        _log(f"  💰{why} {nm} @{cur:,.0f} ({ret:+.2f}%) "
                             f"고점{s['peak']:,.0f} 이론{trig:,.0f} ★지연 {lag:+.3f}% "
                             f"누적{s['realized']:+.2f}%")
                        s["pos"] = False
                        s["low"] = cur
                        s["qty"] = 0
                        if why in ("시간청산",) or s["re"] >= MAX_RE or hm >= EXIT_HM:
                            s["done"] = True
                            shared.release(code, today)     # [7/16] 완전종료 → 슬롯 반환(로테이션)
                    else:
                        # ★[7/16 친구님 승인 ㉮] 접수OK ≠ 팔림 — 체결확인 후에만 '팔림' 기록(유령 매도 방지)
                        s["pending_sell"] = {"qty": int(s["qty"]), "px": cur, "ret": round(ret, 3),
                                             "why": why, "ono": "", "known": kn,
                                             "since": (now - timedelta(seconds=2)).strftime("%H:%M:%S"),
                                             "sent": time.time()}
                        _log(f"  💰{why} {nm} @{cur:,.0f} ({ret:+.2f}%) 접수 → 체결확인 대기 "
                             f"(고점{s['peak']:,.0f} 이론{trig:,.0f} ★지연 {lag:+.3f}%)")
                    dirty = True

            # ── 현금 상태 → ★저점 대비 +0.3% 반등하면 그 종목만 재매수 ──
            else:
                if hm >= EXIT_HM:
                    s["done"] = True; shared.release(code, today); dirty = True
                    continue
                if s["re"] >= MAX_RE:
                    s["done"] = True; shared.release(code, today); dirty = True
                    continue
                if not s["low"] or cur < s["low"]:
                    s["low"] = cur; dirty = True
                    continue
                trig = s["low"] * (1 + BUY_UP / 100)
                # ★[7/15] crash 모드면 재매수(눌림 바닥)에도 급락주 바닥패턴 = 체결강도 ≥ BUY_CHE 게이트
                che_ok = (SELL_MODE != "crash") or (_che(code) >= BUY_CHE)
                if cur >= trig and che_ok:
                    qty = QTY_FIX if QTY_FIX > 0 else int(float(s["cap"]) // cur)   # ★그 종목 전용 예산으로만
                    if qty < 1:
                        continue
                    kn = _known_onos(br, code, "매수")   # ★[지침서5] 발주 직전 주문번호 스냅샷
                    st = br.order(code, qty, "BUY")
                    ok = st in ("OK", "TIMEOUT", "SHADOW")
                    lag = (cur - trig) / trig * 100 if trig else 0.0   # ★+면 이론가보다 비싸게 삼
                    re_disp = s["re"] + (1 if ok else 0)
                    if ok and st == "SHADOW":
                        s["re"] += 1
                        s["pos"] = True
                        s["qty"] = qty
                        s["entry"] = cur
                        s["peak"] = cur
                        s["low"] = 0.0
                    elif ok:
                        # ★[7/16 수술③ 유령왕복] 접수OK ≠ 체결 — 체결확인 후에만 보유 전환(재매수도 동일 구멍).
                        #   확인 전엔 pos/re/low 안 건드림 → 유령이면 현금 상태 그대로 복귀.
                        s["pending_buy"] = {
                            "qty": qty, "px": cur, "re": int(s["re"]) + 1, "ono": "", "known": kn,
                            "since": (now - timedelta(seconds=2)).strftime("%H:%M:%S"),
                            "sent": time.time(),
                        }
                    _log(f"  ↩️재매수#{re_disp} {nm} @{cur:,.0f} x{qty} "
                         f"저점{trig / (1 + BUY_UP / 100):,.0f} 이론{trig:,.0f} ★지연 {lag:+.3f}%"
                         + ("" if st == "SHADOW" or not ok else " (체결확인 대기)"))
                    _lag_row({"일자": today, "시각": now.strftime("%H:%M:%S"), "종목코드": code,
                              "종목명": nm, "방향": "BUY", "사유": f"재매수#{re_disp}",
                              "고점": "", "저점": round(trig / (1 + BUY_UP / 100)),
                              "★이론트리거가": round(trig), "★지시시점현재가": round(cur),
                              "★지연퍼센트": round(lag, 3), "수량": qty,
                              "진입가": round(cur), "수익퍼센트": "",
                              "재매수회차": re_disp, "주문결과": st})
                    dirty = True

        if dirty:
            _jsave(LEDGER, L)
        time.sleep(LOOP_SEC)

    # ══ 마감 요약 ══
    if datetime.now().strftime("%H%M") >= EXIT_HM and L.get("slots"):
        tot = sum(float(s.get("realized") or 0) for s in L["slots"].values())
        n = len(L["slots"])
        _log("─" * 78)
        for code, s in L["slots"].items():
            _log(f"  {s.get('name')}({code}) 재매수{s.get('re')}회 → {float(s.get('realized') or 0):+.2f}%"
                 + (f" (실체결 {float(s['real_realized']):+.2f}%)"
                    if s.get("real_realized") is not None else ""))
        _log(f"★합계 {tot:+.2f}%  ·  평균 {tot / n if n else 0:+.2f}%  "
             f"·  추정손익 {tot / 100 * CAP:+,.0f}원")
        # ★[2026-07-20 친구님 승인 ㉮] 실체결 기준 정산 병기 — 위 줄은 신호가·지시가 기준 낙관치.
        if any(s.get("real_won") is not None for s in L["slots"].values()):
            rtot = sum(float(s.get("real_realized") or 0) for s in L["slots"].values())
            rwon = sum(float(s.get("real_won") or 0) for s in L["slots"].values())
            _log(f"★실체결 정산 {rtot:+.2f}%  ·  {rwon:+,.0f}원 (수수료·세금 전 — 괴리 상세는 {SLIPCSV})")
        _log(f"★8초 지연 실측 → {LAGCSV}  (평균 지연이 0.4% 넘으면 스윙 폐기·홀딩으로 롤백)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
