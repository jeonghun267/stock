# -*- coding: utf-8 -*-
"""[반전 통합 엔진 v2 — 친구님 2026-07-04 설계도 반영] 기존 3개(2양봉/딥V/flow)에서 핵심만 뽑아 하나로.
설계 핵심: ★2·3차 재하락해도 '당일 최저(LL)'를 계속 쫓아가 진짜 최저 바닥에서, ★키움 매수자우위(체결강도) 전환을 보고 산다.
  기존 flow 대비 변경: BoS(직전고점 돌파) 필수 삭제 — "더 높이 사게" 만들어 바닥 놓침(397030 che152·214150 che159 다 놓침).
                        → che 매수우위(≥CHE_MIN)를 트리거로. 최저 추적은 유지(최저까지 쫓기).

★매수(전부 만족):
  ① 급락      : 당일 고점 대비 -DROP%↓
  ② 투매      : 최근 5봉 중 '5선 아래 음봉' 3개↑  (친구님 "3분봉 3개↑ 하락 = 바닥")
  ③ 최저추적LL: LL=당일 최저(재하락마다 갱신=2·3차 쫓아감). 매수 후 LL 깨면 구조붕괴 손절.
  ④ 반등시작  : 최저가 BOTTOM_LAG봉 이상 전 (지금 신저점 만드는 중 아님 = 칼 안잡음)
  ⑤ 바닥권    : 현재가 ≤ LL×(1+NEAR%)  (최저 부근에서만·추격 금지)
  ⑥ 양봉      : 현재가 > 현재봉 시가
  ⑦ ★매수자우위: 체결강도 che ≥ CHE_MIN  (매도자→매수자 우위·유일한 해법). 전환(직전<100→현재≥100)은 별도 기록.
  (+대장만·거래량↑·진입~ENTRY_END)  ※BoS 없음

★매도(통합): 하드-DROP / 구조붕괴(현재가<LL) / 익절트레일(+ARM%후 고점-GIVE%·단 che≥CHE_MIN이면 홀드) / EOD

★안전: RUNIFIED_LIVE=NO(기본)=그림자(주문0·시그널만 기록). 실탄 setx RUNIFIED_LIVE YES. 전부 env 토글.
TR보호: 대장 중 20선 아래(반전구역)만 3분봉 조회 + 60s 캐시.
데이터: opt10080 3분봉 + live_micro_snapshot(체결강도). 출력 data/reversal_unified/.
"""
import os, sys, json, uuid, csv, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")

# ── 설정(env 롤백) ─────────────────────────────────────────────
LIVE       = os.environ.get("RUNIFIED_LIVE", "NO").strip().upper() == "YES"   # 기본 그림자(주문0)
CAP        = int(float(os.environ.get("SAFEPLUS_CAP_KRW") or "300000"))
TOPN       = int(os.environ.get("RUNIFIED_TOPN", "3"))
LEADER_TOPN= int(os.environ.get("RUNIFIED_LEADER_TOPN", "80"))
SCALP_UNI  = os.environ.get("RUNIFIED_SCALP_UNI", "YES").strip().upper() == "YES"  # [7/6 친구님] 유니버스=단타선별. 끄기 setx RUNIFIED_SCALP_UNI NO
DROP_MIN   = float(os.environ.get("RUNIFIED_DROP", "3.0"))       # 급락폭(당일고점대비%)
NEAR_MAX   = float(os.environ.get("RUNIFIED_NEAR", "3.0"))       # 바닥권(LL+%이내)
BOTTOM_LAG = int(os.environ.get("RUNIFIED_BOTTOM_LAG", "1"))     # 최저가 이 봉수 이상 전(반등시작·신저점 아님)
CHE_MIN    = float(os.environ.get("RUNIFIED_CHE_MIN", "100"))    # ★매수자우위 하한
CHE_FLIP   = os.environ.get("RUNIFIED_CHE_FLIP", "NO").strip().upper() == "YES"  # YES면 '전환'(직전<100→현재≥100)까지 요구. 기본 NO(매수우위 레벨로 매수·전환은 기록만)
# ★[2026-07-04 친구님 "지금 나온 최저(저점반등)로 해"] 트리거 교체: che 절대값 → '당일 che 저점 대비 +REB_PT 반등'.
#   근거: 급락 바닥에선 che가 100까지 못 참(005290 바닥 58→60·087010 종일 66~84) = 절대값은 늦은 확인.
#   백테(5일·gate/매도 동일): 절대값100 19건 승률42.1% 건당+0.08% vs 저점반등+8pt 33건 66.7% +1.22%(평균 바닥+1.74%서 매수).
#   min은 09:10 이후 스냅만(개장 극단값 오염 방지)·표본 REB_MINN개 이상. ⚠️표본 5일=잠정, 실로그로 재검. 롤백 setx RUNIFIED_TRIG ABS.
TRIG      = os.environ.get("RUNIFIED_TRIG", "REBOUND").strip().upper()   # REBOUND(저점반등·기본) / ABS(che>=CHE_MIN)
REB_PT    = float(os.environ.get("RUNIFIED_REB_PT", "8"))                # 저점 대비 반등 포인트
REB_MINN  = int(os.environ.get("RUNIFIED_REB_MINN", "5"))                # min 계산 최소 표본수
VOL_RISE   = os.environ.get("RUNIFIED_VOL_RISE", "YES").strip().upper() == "YES"
# [7/4 170920 검증] 거래량↑ 비교가 '진행중 봉 1분치 vs 직전 완성봉 3분치'라 분초반 구조적 탈락 → 3분 환산 보정. 롤백 NO.
VOL_PRORATE= os.environ.get("RUNIFIED_VOL_PRORATE", "YES").strip().upper() == "YES"
# [7/4 친구님 "바닥 시간 너무 늦어, 9시 8분부터 들어가"] 3분봉 8봉=09:24 이전 블라인드 해결:
#   장초반(~M1_END) 3분봉 게이트 미충족이면 1분봉으로 동일 게이트 재검사(8봉=09:08부터 가능·투매 3봉=3분). 롤백 NO.
M1_EARLY   = os.environ.get("RUNIFIED_M1_EARLY", "YES").strip().upper() == "YES"
M1_END     = os.environ.get("RUNIFIED_M1_END", "0930")
# [7/4 친구님 "꼭지에서 팔고 자금회전"] ①부분익절 +10% 절반(vol_exit.do_partial 공통모듈·통합대장과 동일)
#   ②큰수익되돌림은 170920 검증서 역효과(+8.9%→+4.3%·che 매수우위 되눌림은 회복함) → 기본 0=OFF(env로만).
PARTIAL_ON  = os.environ.get("RUNIFIED_PARTIAL", "YES").strip().upper() == "YES"
# ★[2026-07-04 친구님 "장마감 안 간다·급반등 후 바로 매도·한번 더 회전·상한가만 예외"] 익절목표 즉시 전량매도.
#   백테(5일·저점반등 진입): 끌기+장마감 승률63.6% 건당+1.06% → +3% 즉시매도 72.7% +1.62%(보유 132→87분·회전↑).
#   상한가는 위 limitup_hold가 선처리(익일 시가매도). 끄기 setx RUNIFIED_TP 0 (트레일/장마감 폴백은 유지).
TP_NOW      = float(os.environ.get("RUNIFIED_TP", "3"))
# ★[2026-07-04 친구님 최종 "매도자우위로 가자·체결강도 좀 더 주고"] 꼭지신호+매도자우위 매도로 교체(TP보다 우선).
#   매도우위 = 체결강도가 '보유 중 최고' 대비 RECOIL_PT 이상 되꺾임(진입의 저점반등과 대칭). 백테 스윕: -12 최적(승률 61.9%·건당+1.06·런너 +4%이상 2건 살림).
#   매도: ①꼭지신호(고점부 윗꼬리 40%+ 또는 음봉) 발생 후 고점-PEAK_GIVE% & 매도우위 ②5선(3분) 이탈 & 매도우위 ③하드/바닥이탈/상한가/장마감 유지.
#   RECOIL_PT>0이면 TP/트레일 대신 이 방식. 롤백(+3% 전량 복귀): setx RUNIFIED_RECOIL_PT 0.
RECOIL_PT   = float(os.environ.get("RUNIFIED_RECOIL_PT", "12"))
PEAK_GIVE   = float(os.environ.get("RUNIFIED_PEAK_GIVE", "2.0"))
WICK_MIN    = float(os.environ.get("RUNIFIED_WICK_MIN", "0.4"))
# ★[7/4 친구님 "10선 보호" → "5선 타고 가다 매수세 강하면 끌기"] 매도자우위 꺾임이 떠도 가격이 보호선(3분 GUARD_MA선) 위면
#   노이즈로 보고 홀드, 보호선까지 깨질 때 매도. 검증: 5일 패널 무영향(공짜) + 420770 사례 즉시+1.2% → 10선+1.6% → 5선+1.8%(최적).
#   끄기 setx RUNIFIED_GUARD_MA 0 (즉시 매도로 복귀).
GUARD_MA    = int(os.environ.get("RUNIFIED_GUARD_MA", "5"))

# ★[2026-07-05 친구님 "매도자가 많으면 잠시 기다렸다가 확인하고 진입"] 신호 즉시매수 → 확인대기(실전만):
#   신호 분에 안 사고 최대 CONFIRM_WAIT분 관찰. che가 신호시점 이상 회복=그때 매수 / 신호시점 최저(LL) 붕괴·시간초과=취소.
#   취소돼도 조건 살아있으면 재신호로 자연 재도전(놓침 없음). 백테 7/3: 005290 +5.7→+6.9(가짜 09:31 자동취소)·420770 +1.8→+2.1(재신호 더 싼가격).
#   끄기(즉시매수 복귀): setx RUNIFIED_CONFIRM_WAIT 0
CONFIRM_WAIT = int(os.environ.get("RUNIFIED_CONFIRM_WAIT", "3"))

# ★[2026-07-05 친구님 "계단 매수 그림자 하지 말고 바로 실전"] 제2입구(계단식 분산매도 하락용) — 실전.
#   기존 투매V자 게이트가 완만한 계단식 하락(기관 물량흘리기)에선 안 열리는 맹점(에스티팜/제룡 실측) 보완.
#   구조 = 당일고 대비 -STAIR_DROP% 이상 + 당일 VWAP 아래 STAIR_VWAP_N봉(3분) 이상 체류 + 현재가 VWAP 아래 + 신저가 갱신중 아님.
#   트리거(저점+8 반등)·확인대기 3분·매도(-12 되꺾임+5선보호 등)·재진입 3회는 기존 그대로 공유.
#   검증(7/3 브로커 4종목): 에스티팜 +2.4(기존 0→신규)·제룡 +3.8(신규·2회전)·005290 +5.7·기가비스 +3.6(3회전).
#   ⚠️미검증 = 반등 없이 끝까지 무너지는 날 → 하드-3/최저이탈이 방어. 끄기: setx RUNIFIED_STAIR NO
STAIR        = os.environ.get("RUNIFIED_STAIR", "YES").strip().upper() == "YES"
STAIR_DROP   = float(os.environ.get("RUNIFIED_STAIR_DROP", "4.0"))     # 당일고 대비 최소 하락%
STAIR_VWAP_N = int(os.environ.get("RUNIFIED_STAIR_VWAP_N", "10"))     # VWAP 아래 체류 최소 3분봉 수(10=30분)
# ★[2026-07-06 친구님 "계단이 저점서 너무 위에 산다"] 계단 게이트에도 바닥권 상한(near-cap) — 일반게이트 NEAR_MAX와 동일 취지.
#   131290 검증: 매수 237,500 = 당일저 228,500 대비 +3.9% → 이 상한 넘으면 '바닥 아니라 추격'으로 보고 차단. 롤백 setx RUNIFIED_STAIR_NEAR 99
STAIR_NEAR   = float(os.environ.get("RUNIFIED_STAIR_NEAR", "5.0"))    # 계단 진입 허용 = 당일저 +이 % 이내 (극단추격만 차단·정밀필터는 ④ 반등위치)
BIGRUN_TP   = float(os.environ.get("RUNIFIED_BIGRUN_TP", "0"))
BIGRUN_TRAIL= float(os.environ.get("RUNIFIED_BIGRUN_TRAIL", "4.0"))
ENTRY_END  = os.environ.get("RUNIFIED_ENTRY_END", "1400")
EOD_HM     = os.environ.get("RUNIFIED_EOD_HM", "1518")
HARD       = float(os.environ.get("RUNIFIED_HARD", "3.0"))
TRAIL_ARM  = float(os.environ.get("RUNIFIED_TRAIL_ARM", "3.0"))
TRAIL_GIVE = float(os.environ.get("RUNIFIED_TRAIL_GIVE", "2.5"))
MAX_REBUY  = int(os.environ.get("RUNIFIED_MAX_REBUY", "3"))
BARS_TTL   = float(os.environ.get("RUNIFIED_BARS_TTL", "60"))

# ★[2026-07-06 친구님 "SOX -5→-4·기존 엔진에 ①~③ 보강(부분매수 ④는 보류·수량 기존대로)"]
#   ① 레짐·섹터 게이트: 미국 오버나잇 급락(반도체 SOX/나스닥)이면 그 섹터 바닥잡기 진입차단. ② 되돌림 확인. ③ 체결강도 다이버전스.
#   전부 env 토글. 플래그 off면 기존 동작 100% 불변. 매수 수량(CAP/현재가 전량)은 그대로 유지.
REGIME_GATE = os.environ.get("RUNIFIED_REGIME_GATE", "YES").strip().upper() == "YES"   # ① US오버나잇 급락 → 진입차단(기본 ON·차단만 하므로 안전)
SOX_BLOCK   = float(os.environ.get("RUNIFIED_SOX_BLOCK", "-4.0"))   # 반도체 SOX 이 % 이하 → 반도체 종목 진입차단 (친구님 -5→-4)
NQ_BLOCK    = float(os.environ.get("RUNIFIED_NQ_BLOCK",  "-4.0"))   # 나스닥 종합 이 % 이하 → 전체 진입차단 (친구님 -3→-4)
REGIME_MODE = os.environ.get("RUNIFIED_REGIME_MODE", "SECTOR").strip().upper()  # SECTOR(무너진 섹터만·기본)/ALL(risk=DANGER면 전체차단)
US_MAXAGE_H = float(os.environ.get("RUNIFIED_US_MAXAGE_H", "18"))   # us_overnight 신선도(시간)·초과면 게이트 미적용(fail-open)
# ②③ 보강필터: ②=최저 이후 higher-low 형성(되돌림 확인·백테서 '최저봉 고가회복'은 승자 보로노이를 막아 폐기), ③=che 다이버전스.
#   ★[검증] ② '고가회복' 정의는 급락 캡叫션봉 고가가 진입가보다 높아 승자 차단 → 'higher-low 형성'으로 교정.
#   ★FILTER_SHADOW=YES면 평가+CSV기록만 하고 실매매는 차단 안 함(그림자). 실전 하드차단은 setx RUNIFIED_FILTER_SHADOW NO.
HL_CONFIRM   = os.environ.get("RUNIFIED_HL_CONFIRM", "NO").strip().upper() == "YES"   # ② 되돌림 확인(최저 이후 higher-low)
DIV_CONFIRM  = os.environ.get("RUNIFIED_DIV_CONFIRM", "NO").strip().upper() == "YES"  # ③ che 다이버전스(가격 저점갱신 시점 che보다 지금 che 우위)
DIV_PT       = float(os.environ.get("RUNIFIED_DIV_PT", "5"))        # 다이버전스 최소 che 우위 포인트
# ★[2026-07-06 친구님 "10:30도 오름세·고점근처잖아"] ④ 반등위치 필터 — 저점~반등로컬고 구간에서 상단 매수금지(고점추격 방지).
#   검증(오늘): 손실 티에스이 95%(꼭대기)=차단 / 승자 보로노이 47%(중하단)=통과 → 손실주만 깨끗이 걸러냄. near-cap(저점기준)보다 정확.
BOUNCE_CONFIRM= os.environ.get("RUNIFIED_BOUNCE_CONFIRM", "YES").strip().upper() == "YES"
BOUNCE_MAX    = float(os.environ.get("RUNIFIED_BOUNCE_MAX", "70"))  # 저점~반등로컬고 중 이 %초과 지점이면 매수금지
# ★[2026-07-06 친구님 "세력 장난질 감지·프로그램도"] ⑤ 스마트머니 교차검증 — che 매수세여도 외국계/기관이 대량순매도(던짐)면 함정.
#   기존 foreign_supply.py 재사용(거래원 외국계+기관 opt10059·broker호출0·ft_<date>.csv 읽음). ⚠️ft는 5분주기라 지연 → 우선 그림자기록만.
#   검증(오늘): 심텍-112억·원익-108억·주성-90억·인텍-26억 = 큰손던짐 전부 손실 / 보로노이-8억(가벼움)=승자.
SM_CONFIRM   = os.environ.get("RUNIFIED_SM_CONFIRM", "YES").strip().upper() == "YES"
SM_STALE_MIN = float(os.environ.get("RUNIFIED_SM_STALE_MIN", "10"))  # 수급데이터 이 분보다 오래되면 신뢰안함(판정보류)
# ★기존 foreign_supply는 '매도1위 창구=외국계'만 봐서 심텍-138k(대량던짐) 놓침 → 외국계 순매도 '금액' 크기로 판정(검증됨).
SM_KRW       = float(os.environ.get("RUNIFIED_SM_KRW", "-2500000000"))  # 외국계 순매도가 이 금액(원) 이하면 던짐=차단대상 (기본 -25억)
# ★[2026-07-06 친구님 "기관·프로그램이 더 중요"] ⑤에 프로그램매매(opt90013) 추가. 기관(opt10059)은 빈값이라 프로그램으로 대체.
#   검증(키움 실조회): 심텍 프로그램 -24,964·주성 -17,272(백만원) = 대량던짐 손실 / 보로노이 -255(거의0)=승자.
SM_PROG_ON   = os.environ.get("RUNIFIED_SM_PROG", "YES").strip().upper() == "YES"
SM_PROG_TH   = float(os.environ.get("RUNIFIED_SM_PROG_TH", "-10000"))   # 프로그램순매수금액(백만원) 이 값 이하면 던짐 (기본 -100억)
FILTER_SHADOW= os.environ.get("RUNIFIED_FILTER_SHADOW", "YES").strip().upper() == "YES"  # ②③④ 그림자(기본)=차단안하고 기록만
US_JSON     = Path(r"C:\stock_bot\data\us_overnight.json")
SEMI_JSON   = Path(r"C:\stock_bot\config\semi_codes.json")

SNAP = Path(r"C:\stock_bot\IPC\live_micro_snapshot.json")
OUTD = Path(r"C:\stock_bot\data\바닥사냥꾼")          # ★코드네임 BOTTOM HUNTER
POS  = OUTD / "포지션.json"
BOARD= OUTD / "바닥사냥_현황판.txt"                   # 지금 뭘 잡았나(실시간 현황)
CHEST= OUTD / "che_state.json"          # 체결강도 전환감지용(직전값)
BARSC= OUTD / "bars_cache.json"
LOG  = Path(r"C:\stock_bot\data\LOG\바닥사냥꾼.log")
RT_OPEN = Path(r"C:\stock_bot\data\rt_open_positions.json")


def _log(m):
    s = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(s, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        open(LOG, "a", encoding="utf-8").write(s + "\n")
    except Exception:
        pass


def _jload(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {}


def _jsave(p, d):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, p)


def _snap():
    try: return json.loads(SNAP.read_text(encoding="utf-8")).get("codes", {}) or {}
    except Exception: return {}


def _che(sd):
    try:
        v = sd.get("che_str")
        return float(v) if isinstance(v, (int, float)) else None
    except Exception:
        return None


def _ma20(code):
    try:
        import intraday_ma as im
        return float(im.ma(code, 20) or 0.0)
    except Exception:
        return 0.0


_SEMI_CACHE = None
def _is_semi(code):
    """반도체 코드셋(config/semi_codes.json) 조회. 미분류(바이오·금속 등)는 False → 섹터차단에서 제외(살림)."""
    global _SEMI_CACHE
    if _SEMI_CACHE is None:
        try:
            _SEMI_CACHE = set(str(c).zfill(6) for c in (json.loads(SEMI_JSON.read_text(encoding="utf-8")).get("codes") or []))
        except Exception:
            _SEMI_CACHE = set()
    return str(code).zfill(6) in _SEMI_CACHE


def _us_regime():
    """① 미국 오버나잇 레짐 → {block_all, block_semi, sox, nq, risk, fresh, why}.
       파일 없음/오래됨 → fail-open(차단 안 함). 게이트 OFF면 전부 False."""
    r = {"block_all": False, "block_semi": False, "sox": None, "nq": None, "risk": None, "fresh": False, "why": ""}
    if not REGIME_GATE:
        return r
    try:
        d = json.loads(US_JSON.read_text(encoding="utf-8"))
        try:
            age_h = (datetime.now() - datetime.strptime(d.get("ts", ""), "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600.0
        except Exception:
            age_h = 1e9
        r["fresh"] = age_h <= US_MAXAGE_H
        if not r["fresh"]:
            r["why"] = f"US데이터 오래됨({age_h:.0f}h>{US_MAXAGE_H:.0f}h)·게이트미적용"
            return r
        dd = d.get("data") or {}
        def g(k):
            v = dd.get(k, {}); return v.get("chg") if isinstance(v, dict) else None
        r["sox"], r["nq"], r["risk"] = g("sox"), g("nasdaq"), d.get("risk")
        if r["nq"] is not None and r["nq"] <= NQ_BLOCK:
            r["block_all"] = True; r["why"] = f"나스닥 {r['nq']}%≤{NQ_BLOCK:g} 전체차단"
        if REGIME_MODE == "ALL" and r["risk"] == "DANGER":
            r["block_all"] = True; r["why"] = (r["why"] + " / risk=DANGER 전체차단").strip(" /")
        if r["sox"] is not None and r["sox"] <= SOX_BLOCK:
            r["block_semi"] = True; r["why"] = (r["why"] + f" / 반도체SOX {r['sox']}%≤{SOX_BLOCK:g} 반도체차단").strip(" /")
    except Exception as e:
        r["why"] = f"US파싱실패({str(e)[:40]})·게이트미적용"
    return r


_PROG_CACHE = {}
def _prog_net(bc, code, today):
    """⑤ opt90013 오늘 프로그램순매수금액(백만원). 60s 캐시·broker호출. 실패시 None(=판정보류)."""
    if not SM_PROG_ON:
        return None
    try:
        e = _PROG_CACHE.get(code)
        if e and (time.time() - e[0]) < 60:
            return e[1]
        r = bc.tr("opt90013", inputs={"시간일자구분": "1", "금액수량구분": "1", "종목코드": code},
                  output_fields=["일자", "프로그램순매수금액"], timeout_sec=6.0, screen_no="9722")
        recs = ((r or {}).get("data") or {}).get("records") or []
        val = None
        for d in recs:
            if str(d.get("일자")) == today:
                try:
                    val = int(float(str(d.get("프로그램순매수금액", "0")).replace(",", "") or 0))
                except Exception:
                    val = None
                break
        _PROG_CACHE[code] = (time.time(), val)
        return val
    except Exception:
        return None


def stair_gate(bars, cur):
    """[7/5 계단식 제2입구] 완만한 분산매도 하락 구조 판정 — 투매 불요. bars=오늘 3분봉 [(hm,o,h,l,c,v)].
    반환은 gate()와 동일 규격(ok/LL/off/drop/tf) → 이후 트리거·확인대기·매도 흐름 공유."""
    if len(bars) < STAIR_VWAP_N + 2:
        return {"ok": False}
    day_hi = max(b[2] for b in bars); day_lo = min(b[3] for b in bars)
    if day_hi <= 0 or day_lo <= 0 or (day_hi - cur) / day_hi * 100 < STAIR_DROP:
        return {"ok": False}
    cum_pv = 0.0; cum_v = 0.0; below = 0
    for b in bars:
        cum_pv += b[4] * b[5]; cum_v += b[5]
        vw = cum_pv / cum_v if cum_v > 0 else 0.0
        if vw > 0 and b[4] < vw:
            below += 1
    vwap = cum_pv / cum_v if cum_v > 0 else 0.0
    if not (vwap > 0 and cur < vwap and below >= STAIR_VWAP_N):
        return {"ok": False}
    if bars[-1][3] <= day_lo:                      # 현재 봉이 당일최저 만드는 중 = 신저가 진행 → 매수금지
        return {"ok": False}
    off = (cur / day_lo - 1) * 100 if day_lo > 0 else 999
    if off > STAIR_NEAR:                           # ★바닥권 상한: 저점서 너무 위면 추격 → 차단(131290 +3.9% 사례)
        return {"ok": False, "off": off, "why": f"계단바닥권초과(+{off:.1f}%)"}
    return {"ok": True, "LL": day_lo, "off": off,
            "drop": (day_hi - day_lo) / day_hi * 100, "tf": "계단"}


def _bars(bc, code, cache, tick="3"):
    """opt10080 오늘 분봉 [(hm,o,h,l,c,v)] · 60s 디스크캐시(TR보호). tick='1'이면 1분봉(장초반 조기감지용·캐시키 분리)."""
    ck = code if tick == "3" else f"{code}@{tick}"
    e = cache.get(ck)
    if isinstance(e, dict) and (time.time() - float(e.get("ts", 0))) <= BARS_TTL and e.get("bars"):
        return [tuple(x) for x in e["bars"]]
    def ff(x):
        try: return abs(float(str(x).replace(",", "")))
        except Exception: return 0.0
    try:
        r = bc.tr("opt10080", inputs={"종목코드": code, "틱범위": tick, "수정주가구분": "1"},
                  output_fields=["체결시간", "시가", "고가", "저가", "현재가", "거래량"], timeout_sec=6.0, screen_no="9720")
        today = datetime.now().strftime("%Y%m%d"); out = []
        for z in (((r or {}).get("data") or {}).get("records") or [])[::-1]:
            ts = str(z.get("체결시간", ""))
            if ts[:8] != today: continue
            out.append((ts[8:12], ff(z.get("시가")), ff(z.get("고가")), ff(z.get("저가")), ff(z.get("현재가")), ff(z.get("거래량"))))
        if out:
            cache[ck] = {"ts": time.time(), "bars": out}
        return out
    except Exception:
        return []


def gate(bars, cur, hm=None):
    """★반전 바닥 구조(BoS 없음). 반환 dict(ok·LL·drop·off·why). che는 run().
       hm(현재 HHMM) 주면 진행중 봉 거래량을 3분 환산해 거래량↑ 비교(분초반 불공정 보정)."""
    if len(bars) < 8:
        return {"ok": False, "why": "봉부족", "LL": 0}
    cl = [b[4] for b in bars]
    def m5(k): return sum(cl[max(0, k - 4):k + 1]) / min(5, k + 1)
    cap = sum(1 for k in range(len(bars) - 5, len(bars))
              if bars[k][4] < bars[k][1] and bars[k][4] < m5(k)) >= 3           # ②투매
    lows = [b[3] for b in bars]; LL = min(lows); LLi = lows.index(LL)           # ③최저추적
    HH = max(b[2] for b in bars)
    drop = (HH - LL) / HH * 100 if HH > 0 else 0                                # ①급락폭
    bottom_passed = (len(bars) - 1 - LLi) >= BOTTOM_LAG                         # ④반등시작(신저점 아님)
    off = (cur / LL - 1) * 100 if LL > 0 else 999
    near = off <= NEAR_MAX                                                      # ⑤바닥권
    green = cur > bars[-1][1]                                                   # ⑥양봉
    vol_now = bars[-1][5]
    if VOL_PRORATE and hm:
        try:
            el = (int(hm[:2]) * 60 + int(hm[2:])) - (int(bars[-1][0][:2]) * 60 + int(bars[-1][0][2:])) + 1
            if 1 <= el < 3: vol_now = vol_now * 3.0 / el      # 진행중 봉 3분 환산
        except Exception: pass
    vol_rise = (not VOL_RISE) or (len(bars) >= 2 and vol_now > bars[-2][5])     # 거래량↑
    ok = cap and drop >= DROP_MIN and bottom_passed and near and green and vol_rise
    det = []
    if not cap: det.append("투매✗")
    if drop < DROP_MIN: det.append(f"급락✗({drop:.1f}%)")
    if not bottom_passed: det.append("신저점중✗")
    if not near: det.append(f"바닥권✗(+{off:.1f}%)")
    if not green: det.append("양봉✗")
    if not vol_rise: det.append("거래량✗")
    return {"ok": ok, "LL": LL, "LLi": LLi, "drop": drop, "off": off, "why": "·".join(det) or "구조통과"}


def _order(bc, code, qty, side, tag, live):
    if not (LIVE and live):
        return True
    try:
        ai = bc.account_info("ACCNO")
        accs = (ai.get("data") or {}).get("accounts") or []
        if isinstance(accs, str): accs = [a for a in accs.split(";") if a]   # [7/6 근본수정] 브로커가 "계좌번호;" 세미콜론 문자열로 줌
        acc = (accs[0] if isinstance(accs, list) and accs else "") or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()  # env 폴백(계좌조회 타임아웃 방어)
        if not acc:
            _log(f"[{tag}] 계좌없음"); return False
        r = bc.send_order_real(idempotency_key=f"runi_{side.lower()}_{code}_{uuid.uuid4()}", account=acc,
                               code=code, qty=int(qty), order_type=(1 if side == "BUY" else 2), price=0,
                               hoga_gb="06", rqname=f"RUNI_{side}_{code}", screen_no="9721")
        st = str((r or {}).get("status", "")).upper()
        ok = (st in ("OK", "TIMEOUT")) if side == "BUY" else (st == "OK")
        _log(f"[LIVE] {side} {code} x{qty} status={st} → {'성공' if ok else '실패'}")
        return ok
    except Exception as e:
        _log(f"[{tag}] 주문실패 {e}"); return False


def run():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < "0901" or hm > "1530":
        return
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            _log("broker dead → skip"); return
        bc = BrokerClient()
    except Exception as e:
        _log(f"broker 연결실패 {e}"); return
    OUTD.mkdir(parents=True, exist_ok=True)
    snap = _snap(); pos = _jload(POS)
    che_state = _jload(CHEST); che_state = che_state if che_state.get("date") == today else {"date": today}
    bars_cache = _jload(BARSC); bars_cache = bars_cache if isinstance(bars_cache, dict) else {}
    mode = "[LIVE]" if LIVE else "[그림자]"

    # ===== 매도관리 =====
    try:
        import limitup_exit as LU
    except Exception:
        LU = None
    for c, p in list(pos.items()):
        if not isinstance(p, dict) or p.get("status") != "HOLDING":
            continue
        # ★상한가 오버나잇 홀드 → 익일 시가매도(전 전략 공통)
        if LU and LU.should_open_sell(p, today, hm):
            sd = snap.get(c) or {}; cur = float(sd.get("cur", 0) or 0)
            if cur <= 0:
                b = _bars(bc, c, bars_cache); cur = b[0][1] if b else 0.0
            if cur > 0:
                _order(bc, c, int(p.get("qty", 0) or 0), "SELL", "익일시가매도", p.get("live"))
                p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = "익일시가매도(상한가)"; p["sell_hm"] = hm
                _log(f"{mode} SELL {c} @{cur:,.0f} 익일시가매도(상한가) 매수{p.get('buy_price',0):,.0f}")
                if p.get("live"):
                    try:
                        import rt_registry as _RT; _RT.remove(c)   # [7/5] 공용장부 제거
                    except Exception:
                        pass
            continue
        if p.get("date") != today:
            continue
        sd = snap.get(c) or {}
        cur = float(sd.get("cur", 0) or 0)
        if cur <= 0:
            b = _bars(bc, c, bars_cache); cur = b[-1][4] if b else 0.0
        if cur <= 0:
            continue
        buy = float(p.get("buy_price", 0) or 0); LL = float(p.get("LL", 0) or 0)
        che = _che(sd); peak = max(float(p.get("peak", buy) or buy), cur); p["peak"] = peak
        # ★상한가 도달 → 당일 안 팔고 익일 시가매도 예약(홀드)
        if LU and LU.is_limitup(c, cur):
            if not p.get("limitup_hold"):
                p["limitup_hold"] = True; p["exit_plan"] = "익일시가매도(상한가)"
                _log(f"{mode} 🔒상한가 {c} @{cur:,.0f} → 오늘 홀드·익일 시가매도 예약")
            continue
        # ★부분익절: +10% 도달 시 절반 매도(공통모듈·1회) — 꼭지 부근 이익확정+자금회전
        if PARTIAL_ON and hm < EOD_HM:
            try:
                import vol_exit as _VEp
                _VEp.do_partial(p, cur, lambda q, t: _order(bc, c, q, "SELL", t, p.get("live")), str(RT_OPEN), _log)
            except Exception:
                pass
        # ★[7/4 친구님 최종 "매도우위 확인되면 바로 판다·-2%는 보험"] 보유 중 체결강도 최고 추적
        if RECOIL_PT > 0:
            if che is not None:
                p["che_pk"] = max(float(p.get("che_pk", che) or che), che)
            b = _bars(bc, c, bars_cache)
            _ma5 = (sum(x[4] for x in b[-5:]) / min(5, len(b))) if b else 0.0
            _maG = (sum(x[4] for x in b[-GUARD_MA:]) / min(GUARD_MA, len(b))) if (b and GUARD_MA > 0) else 0.0
            _cpk = float(p.get("che_pk", 0) or 0)
            seller_dom = (che is not None and _cpk > 0 and che <= _cpk - RECOIL_PT)   # 매도자우위 = 체결강도 되꺾임(실측상 가격 고점-2% 부근에서 발동)
            if GUARD_MA > 0 and seller_dom and _maG > 0 and cur >= _maG:
                seller_dom = False                                                     # ★보호선(기본 5선): 가격이 선 위면 꺾임을 노이즈로 간주·선 깨질 때 매도(하드/바닥이탈은 별도)
        sell = None
        if buy > 0 and (cur / buy - 1) * 100 <= -HARD:
            sell = f"하드-{HARD:g}%"
        elif LL > 0 and cur < LL:
            sell = "구조붕괴(최저LL이탈)"
        elif RECOIL_PT > 0 and seller_dom:
            sell = f"매도자우위(체결강도 최고-{RECOIL_PT:g} 되꺾임) 즉시"   # ★주 매도: 확인 즉시·대기 없음
        elif RECOIL_PT > 0 and che is None and cur <= peak * (1 - PEAK_GIVE / 100.0):
            sell = f"보험 고점-{PEAK_GIVE:g}%(체결강도 공백)"             # 보험: 데이터 끊겼을 때만
        elif RECOIL_PT > 0 and che is None and _ma5 > 0 and cur < _ma5:
            sell = "보험 5선이탈(체결강도 공백)"
        elif RECOIL_PT <= 0 and buy > 0 and TP_NOW > 0 and (cur / buy - 1) * 100 >= TP_NOW:
            sell = f"급반등익절+{TP_NOW:g}%"                    # 폴백(RECOIL 끄면): 목표 즉시 전량
        elif RECOIL_PT <= 0 and buy > 0 and BIGRUN_TP > 0 and (peak / buy - 1) * 100 >= BIGRUN_TP and cur <= peak * (1 - BIGRUN_TRAIL / 100.0):
            sell = f"큰수익되돌림(고점-{BIGRUN_TRAIL:g}%)"
        elif RECOIL_PT <= 0 and buy > 0 and (peak / buy - 1) * 100 >= TRAIL_ARM and cur <= peak * (1 - TRAIL_GIVE / 100.0) and (che is None or che < CHE_MIN):
            sell = f"익절트레일(고점-{TRAIL_GIVE:g}%)"
        elif hm >= EOD_HM:
            sell = "EOD청산"
        if sell:
            _order(bc, c, int(p.get("qty", 0) or 0), "SELL", sell, p.get("live"))
            p["status"] = "DONE"; p["sell_price"] = cur; p["exit"] = sell; p["sell_hm"] = hm
            _log(f"{mode} SELL {c} @{cur:,.0f} ({(cur/buy-1)*100:+.1f}%) {sell}")
            if p.get("live"):
                try:
                    import rt_registry as _RT; _RT.remove(c)   # [7/5] 공용장부 제거
                except Exception:
                    pass
    _jsave(POS, pos)

    # ===== 진입 =====
    board = [f"=== 반전통합v2 {mode} {now:%H:%M} (급락+투매+최저추적+바닥권+양봉+che≥{CHE_MIN:.0f}·BoS없음) ==="]
    held = sum(1 for p in pos.values() if isinstance(p, dict) and p.get("date") == today and p.get("status") == "HOLDING")
    budget_block = False
    try:
        import position_budget as gb
        if gb.budget_on() and gb.remaining_intraday() <= 0:
            budget_block = True; board.append("  [전역상한] 신규진입 보류")
    except Exception:
        pass
    if hm <= ENTRY_END and held < TOPN and not budget_block:
        uni = []
        if SCALP_UNI:                                 # [7/6 친구님] 거래대금 대신 단타 선별(scalp) 유니버스
            try:
                _bd = json.load(open(r"C:\stock_bot\data\daily_leader_board.json", encoding="utf-8"))
                uni = [str(c).zfill(6) for c in (_bd.get("codes") or [])][:LEADER_TOPN]
            except Exception:
                uni = []
        if not uni:
            try:
                import leader_filter as lf
                uni = list(lf.leader_list(bc) or [])[:LEADER_TOPN]
            except Exception:
                uni = []
        excl = {str(k).zfill(6) for k, v in _jload(RT_OPEN).items() if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0}
        pend_all = che_state.get("_pend") if isinstance(che_state.get("_pend"), dict) else {}   # [확인대기] 코드별 신호 보류(일 단위 자동리셋)
        che_state["_pend"] = pend_all
        _RG = _us_regime(); _rg_logged = 0     # ① 미국 오버나잇 레짐(1회 계산)
        if _RG.get("block_all") or _RG.get("block_semi"):
            board.append(f"  🛑 [레짐게이트] {_RG.get('why','')} (SOX={_RG.get('sox')}·나스닥={_RG.get('nq')}·risk={_RG.get('risk')})")
            _log(f"{mode} 레짐게이트 발동: {_RG.get('why','')}")
        for code in uni:
            if held >= TOPN:
                break
            code = str(code).zfill(6)
            sd = snap.get(code) or {}
            che = _che(sd)
            _cs = che_state.get(code)
            prev = _cs.get("last") if isinstance(_cs, dict) else _cs   # 직전(1분전) che (구형 스칼라 호환)
            if che is not None:
                _cs = _cs if isinstance(_cs, dict) else {}
                _cs["last"] = che
                if hm >= "0910":                 # [REBOUND] 당일 최저 che 추적(개장 극단값 제외)
                    _cs["min"] = che if _cs.get("min") is None else min(float(_cs["min"]), che)
                    _cs["n"] = int(_cs.get("n", 0)) + 1
                    _pc = float(sd.get("cur", 0) or 0)     # ③[다이버전스] 당일 '가격최저' 갱신 시점의 che 스냅
                    if _pc > 0 and (_cs.get("plow") is None or _pc < float(_cs["plow"])):
                        _cs["plow"] = _pc; _cs["che_at_plow"] = che
                che_state[code] = _cs
            # ① [레짐·섹터 게이트] 미국 오버나잇 급락 → 진입차단(확인대기도 취소)
            if _RG.get("block_all") or (_RG.get("block_semi") and _is_semi(code)):
                if code in pend_all:
                    pend_all.pop(code, None)
                if _rg_logged < 6:
                    _rg_logged += 1
                    _why = "전체급락" if _RG.get("block_all") else f"반도체(SOX{_RG.get('sox')})"
                    board.append(f"    🛑 {code} 레짐차단 [{_why}]")
                continue
            if code in excl:
                continue
            he = pos.get(code)
            if isinstance(he, dict) and he.get("date") == today:
                if he.get("status") == "HOLDING": continue
                if int(he.get("buys", 0)) >= MAX_REBUY: continue
            pd = pend_all.get(code)
            if isinstance(pd, dict):                       # ★[확인대기] 신호 떠서 관찰 중 — 매수/취소 판정
                cur = float(sd.get("cur", 0) or 0)
                if cur <= 0:
                    _pb = _bars(bc, code, bars_cache)
                    cur = _pb[-1][4] if _pb else 0.0
                pd["n"] = int(pd.get("n", 0)) + 1
                LLp = float(pd.get("LL", 0) or 0)
                if cur > 0 and LLp > 0 and cur < LLp:      # 대기 중 신저가 = 가짜바닥이 스스로 무너짐
                    pend_all.pop(code, None)
                    board.append(f"  ✖ {code} 확인대기 취소 — 대기중 최저({LLp:,.0f}) 붕괴 @{cur:,.0f}")
                    _log(f"{mode} WAIT-CANCEL {code} @{cur:,.0f} 최저붕괴({LLp:,.0f})")
                elif held >= TOPN:
                    pend_all.pop(code, None)
                    board.append(f"  ✖ {code} 확인대기 취소 — 보유한도")
                elif che is not None and che >= float(pd.get("che0", 1e9)):   # 매수세 유지/회복 확인 = 진입
                    pend_all.pop(code, None)
                    if cur > 0:
                        qty = max(1, int(CAP / cur))
                        _ok = _order(bc, code, qty, "BUY", f"확인진입 최저{LLp:,.0f}", LIVE)
                        if LIVE and _ok:
                            try:
                                import rt_registry as _RT; _RT.register(code, qty, cur, "RUNIFIED")
                            except Exception:
                                pass
                        if _ok:                                          # [7/6 유령방지] 주문 성공(그림자 포함)일 때만 기록
                            buys = (int(he.get("buys", 0)) + 1) if (isinstance(he, dict) and he.get("date") == today) else 1
                            pos[code] = {"code": code, "status": "HOLDING", "buy_price": cur, "qty": qty, "peak": cur,
                                         "LL": LLp, "che": che, "che_flip": False, "drop": float(pd.get("drop", 0) or 0),
                                         "date": today, "buy_hm": hm, "live": LIVE, "buys": buys}
                            held += 1
                            _log(f"{mode} BUY {code} @{cur:,.0f} [확인{pd.get('n',0)}분] 최저{LLp:,.0f} che {pd.get('che0')}→{che} ({buys}/{MAX_REBUY})")
                elif int(pd.get("n", 0)) >= CONFIRM_WAIT:  # 시간초과 = 매수세 식음
                    pend_all.pop(code, None)
                    board.append(f"  ✖ {code} 확인대기 취소 — {CONFIRM_WAIT}분 내 매수세 미확인(che {pd.get('che0')}→{che})")
                    _log(f"{mode} WAIT-CANCEL {code} 시간초과 che{pd.get('che0')}→{che}")
                else:
                    board.append(f"  ⏳ {code} 매수세 확인대기 {pd.get('n',0)}/{CONFIRM_WAIT} (che {pd.get('che0')}→{che})")
                continue
            cur = float(sd.get("cur", 0) or 0)
            # TR보호 사전필터: 20선 아래(반전구역)만 봉조회. cur 없으면(미구독) 봉으로 확인.
            ma20 = _ma20(code)
            if cur > 0 and ma20 > 0 and cur >= ma20:
                continue                         # 20선 위 = 반전대상 아님
            bars = _bars(bc, code, bars_cache)
            if not bars:
                continue
            if cur <= 0:
                cur = bars[-1][4]
            if ma20 > 0 and cur >= ma20:
                continue
            g = gate(bars, cur, hm)
            g["tf"] = "3분"
            if not g["ok"] and M1_EARLY and hm <= M1_END:
                b1 = _bars(bc, code, bars_cache, tick="1")     # ★장초반 1분봉 조기감지(09:08~)
                if b1:
                    g1 = gate(b1, cur, None)                   # 1분봉은 3분환산 보정 없이
                    if g1["ok"]:
                        g = g1; g["tf"] = "1분"
            if not g["ok"] and STAIR:                          # ★[7/5] 제2입구: 계단식 분산매도 하락(투매 없이도)
                gs = stair_gate(bars, cur)
                if gs.get("ok"):
                    g = gs
            if not g["ok"]:
                continue
            if TRIG == "REBOUND":               # ★저점반등: 당일 che 최저 대비 +REB_PT 돌아섬(절대값 무관)
                _st = che_state.get(code) if isinstance(che_state.get(code), dict) else {}
                che_dom = (che is not None and _st.get("min") is not None
                           and int(_st.get("n", 0)) >= REB_MINN and che >= float(_st["min"]) + REB_PT)
            else:
                che_dom = (che is not None and che >= CHE_MIN)
            is_flip = (che is not None and che >= CHE_MIN) and (prev is None or prev < CHE_MIN)
            LL = g["LL"]
            # ★[2026-07-06] ②③④⑤ 보강필터 — 진입후보(che_dom)일 때만 평가·그림자CSV 기록. FILTER_SHADOW면 차단안함(실매매 불변).
            if che_dom and (HL_CONFIRM or DIV_CONFIRM or BOUNCE_CONFIRM or SM_CONFIRM):
                hl_ok = True; div_ok = True; bounce_ok = True; bpos = -1.0; sm_ok = True; sm_info = ""
                if HL_CONFIRM:                                  # ② 최저 이후 higher-low 형성(되돌림 확인·백테 교정판)
                    _LLi = int(g.get("LLi", 0)); _bafter = bars[_LLi + 1:]
                    hl_ok = any(b[3] > LL for b in _bafter)
                if DIV_CONFIRM:                                 # ③ 가격 저점 갱신 시점 che 대비 지금 che 우위(=흡수)
                    _st3 = che_state.get(code) if isinstance(che_state.get(code), dict) else {}
                    _cap0 = _st3.get("che_at_plow")
                    div_ok = (che is not None and _cap0 is not None and che >= float(_cap0) + DIV_PT)
                if BOUNCE_CONFIRM:                              # ④ 반등위치: 저점~반등로컬고 중 상단 BOUNCE_MAX% 초과면 고점추격 → 금지
                    _LLi = int(g.get("LLi", 0)); _lhi = max((b[2] for b in bars[_LLi:]), default=cur)
                    _rng = _lhi - LL
                    bpos = ((cur - LL) / _rng * 100) if _rng > 0 else 0.0
                    bounce_ok = bpos <= BOUNCE_MAX
                if SM_CONFIRM:                                  # ⑤ 스마트머니: 공용모듈(★실시간 외국인 opt10040 + 프로그램 opt90013). 5분 배치(foreign_supply) 폐기·전 전략과 통일.
                    try:
                        import smart_money as _SM
                        _smblk, sm_info = _SM.dumping(bc, code, cur)   # 진입순간 실시간 조회·던지면 blocked
                        sm_ok = not _smblk
                    except Exception:
                        sm_ok = True; sm_info = "수급NA"
                would_block = (not hl_ok) or (not div_ok) or (not bounce_ok) or (not sm_ok)   # 기록용(②③④⑤ 통합)
                enforce_block = (not bounce_ok) or (not sm_ok)                 # ★실전 하드차단 = ④(반등위치) + ⑤(외국인/프로그램 던지기 회피). ②③은 기록만
                try:
                    _fp = OUTD / f"보강필터_그림자_{today}.csv"; _new = not _fp.exists()
                    with open(_fp, "a", encoding="utf-8-sig", newline="") as _f:
                        _w = csv.writer(_f)
                        if _new: _w.writerow(["hm", "code", "cur", "che", "HL_ok", "DIV_ok", "bounce_pos%", "bounce_ok", "SM_ok", "SM_info", "enforced", "mode"])
                        _w.writerow([hm, code, f"{cur:.0f}", che, hl_ok, div_ok, f"{bpos:.0f}", bounce_ok, sm_ok, sm_info,
                                     (enforce_block and not FILTER_SHADOW), "SHADOW" if FILTER_SHADOW else "LIVE"])
                except Exception:
                    pass
                if enforce_block and not FILTER_SHADOW:         # ★실전 하드차단: ④반등위치 초과 or ⑤외국인/프로그램 던지기
                    _why = []
                    if not bounce_ok: _why.append(f"④반등{bpos:.0f}%>{BOUNCE_MAX:g}")
                    if not sm_ok: _why.append(f"⑤던지기({sm_info})")
                    board.append(f"  ⛔ {code} 실전차단 [{'·'.join(_why)}] (HL={hl_ok}·DIV={div_ok} 기록됨)")
                    _log(f"{mode} FILTER-BLOCK {code} [{'·'.join(_why)}]")
                    if code in pend_all:
                        pend_all.pop(code, None)
                    continue
                elif would_block:
                    board.append(f"  🌓 {code} 그림자차단대상 HL={hl_ok}·DIV={div_ok}·반등{bpos:.0f}%·수급{sm_ok}({sm_info})(②③ 기록만·실매매 진행)")
            # 실전: 매수우위 필수(+CHE_FLIP=YES면 전환까지). 그림자: che 없어도 '구조통과' 기록(커버리지 확인).
            if LIVE:
                if not che_dom or (CHE_FLIP and not is_flip):
                    board.append(f"  ⏸ {code} 구조통과·che대기(che={che} 전환={is_flip})")
                    continue
                if CONFIRM_WAIT > 0:                       # ★[확인대기] 즉시매수 대신 관찰 시작(다음 분부터 판정)
                    pend_all[code] = {"hm": hm, "che0": che, "LL": LL, "drop": round(g["drop"], 1), "n": 0}
                    board.append(f"  ⏳ {code} 신호 @{cur:,.0f} che{che} → 매수세 확인대기(최대 {CONFIRM_WAIT}분)")
                    _log(f"{mode} WAIT {code} 신호@{cur:,.0f} [{g.get('tf','3분')}] 최저{LL:,.0f} che={che} → 확인대기")
                    continue
            qty = max(1, int(CAP / cur)) if cur > 0 else 0
            _ok = _order(bc, code, qty, "BUY", f"진입 최저{LL:,.0f}", LIVE)
            if LIVE and _ok:
                try:
                    import rt_registry as _RT; _RT.register(code, qty, cur, "RUNIFIED")   # [7/5] 공용장부 즉시등록(중복매수·전역한도 시차 제거)
                except Exception:
                    pass
            if not _ok:                                      # [7/6 유령방지] 주문 실패(계좌없음 등)면 기록 스킵 → 다음 후보
                continue
            buys = (int(he.get("buys", 0)) + 1) if (isinstance(he, dict) and he.get("date") == today) else 1
            pos[code] = {"code": code, "status": "HOLDING", "buy_price": cur, "qty": qty, "peak": cur,
                         "LL": LL, "che": che, "che_flip": is_flip, "drop": round(g["drop"], 1),
                         "date": today, "buy_hm": hm, "live": LIVE, "buys": buys}
            held += 1
            tag = "★매수" if che_dom else "★매수후보(che없음·그림자)"
            flg = "🔥전환" if is_flip else ""
            _log(f"{mode} BUY {code} @{cur:,.0f} [{g.get('tf','3분')}] 최저{LL:,.0f}(+{g['off']:.1f}%) 급락{g['drop']:.1f}% che={che}{flg} ({buys}/{MAX_REBUY})")
            board.append(f"  🟢 {tag}{flg} {code} @{cur:,.0f} [{g.get('tf','3분')}] 최저{LL:,.0f} 급락{g['drop']:.0f}% che={che}")
            try:
                f = OUTD / f"바닥사냥_시그널_{today}.csv"; new = not f.exists()
                with open(f, "a", encoding="utf-8-sig", newline="") as fp:
                    w = csv.writer(fp)
                    if new: w.writerow(["hm", "code", "buy", "LL", "off%", "drop%", "che", "che_flip", "tf"])
                    w.writerow([hm, code, f"{cur:.0f}", f"{LL:.0f}", f"{g['off']:.1f}", f"{g['drop']:.1f}", che, is_flip, g.get("tf", "3분")])
            except Exception:
                pass
    for c, p in pos.items():
        if isinstance(p, dict) and p.get("date") == today and p.get("status") == "HOLDING":
            board.append(f"  ● 보유 {c} 매수{p.get('buy_price'):,.0f} 고점{p.get('peak',0):,.0f} 최저LL{p.get('LL',0):,.0f}")
    try:
        BOARD.write_text("\n".join(board) + "\n", encoding="utf-8")
    except Exception:
        pass
    _jsave(POS, pos)
    _jsave(CHEST, che_state)
    _jsave(BARSC, {c: e for c, e in bars_cache.items() if isinstance(e, dict) and (time.time() - float(e.get("ts", 0))) <= 600})


if __name__ == "__main__":
    try:
        run()
    except Exception as ex:
        _log(f"[FATAL] {ex}"); import traceback; traceback.print_exc()
