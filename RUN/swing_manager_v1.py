# -*- coding: utf-8 -*-
"""
[스윙 관리인 v1 2026-06-12 밤 — 친구님 결정 "100만원 넣고 해"]
친구님식 스윙: 대장주(직전 20일 내 대금 1000억+ 2일+, 진입시점 정보만) & 바닥 확인(2일 전
저가가 앞뒤 2일보다 낮음) & 종가가 바닥 대비 5~10% & 매수세(양봉 + 대금 전일比 증가).
손절 = 종가 바닥이탈 → 익일 시가 매도. 보유 = 5거래일 → 익일 시가 매도. 1종목씩, 캡 100만.
백테 근거: leader_swing7_v3 — 순 +1.21%/회·승률 44%·바닥붕괴 41%(손절캡으로 수용).

모드 (인자):
  pick    14:57 — 당일 후보 1등 선정 → SWING_LIVE=YES면 broker 시장가 매수, 아니면 모의 기록
  manage  15:05 — 보유 스윙 점검: 바닥이탈/5일도달 → sell_due 표시
  sell    09:01 — sell_due 표시분 시장가 매도
안전: ①rt_open에 SWING 꼬리표(단타 매도엔진 분리는 strategy!=PULLBACK이라 자동 무간섭)
  ②중복금지: rt_open에 이미 있는 종목(전략 불문) 매수 불가 ③SWING 동시 1종목
  ④SWING_LIVE 기본 NO(모의) — 월요일 친구님 "고" 후 setx SWING_LIVE YES
원장: DATA/swing_positions.json (스윙 전용 장부, rt_open과 별도 + 매수시 rt_open에도 등록[수집보장用])
"""
import csv, io, json, os, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

EOD = Path(r"C:\stock_bot\data\eod_daily_bars.csv")
P1M = Path(r"C:\stock_bot\DATA\prices_1m.csv")
RT_OPEN = Path(r"C:\stock_bot\DATA\rt_open_positions.json")
LEDGER = Path(r"C:\stock_bot\DATA\swing_positions.json")
SHADOW_LEDGER = Path(r"C:\stock_bot\data\shadow\swing_intraday_shadow.json")   # 장중 그림자 전용(실전과 분리)
SHADOW_CSV    = Path(r"C:\stock_bot\data\shadow\swing_intraday_shadow.csv")
LOGF = Path(r"C:\stock_bot\data\LOG\swing_manager.log")

SWING_LIVE = os.environ.get("SWING_LIVE", "NO").strip().upper() == "YES"
SWING_CAP_KRW = int(float(os.environ.get("SWING_CAP_KRW", "1000000")))
SWING_MAX_POS = 1
# [SWING-HOLD4 2026-06-12 밤 ★친구님 "무조건 5일이 맞나" 의심 적중] 만기 그리드(125건):
#   4일 순+1.29%/승47%/-5%↓38% > 5일 +0.94%/41%/44% — 상승다리 중앙 3일이라 5일째는 하락다리.
#   조정: setx SWING_HOLD_DAYS N (3~5).
HOLD_DAYS = int(os.environ.get("SWING_HOLD_DAYS", "4"))
# [HEIGHT-BAND 2026-06-13 ★친구님 지시 "7~10% 고정"] 진입높이 그리드(v5, 1,033건):
#   바닥붕괴율 높이와 단조감소(0~3% 61%→8~10% 27%), 띠 안에서도 초입 5~7%&매수세 순-0.53%/붕괴45%
#   vs 후반 7~10%&매수세 순+1.72%/붕괴29% → 7~10 한정. 공급 0.6→~0.3마리/일(닷새 1번꼴).
#   그림자(19:00)는 5~10 전체 계속 기록 = 5~7 구간 실측 비교 유지. 롤백: setx SWING_HEIGHT_MIN 5.
HEIGHT_MIN = float(os.environ.get("SWING_HEIGHT_MIN", "7"))
HEIGHT_MAX = float(os.environ.get("SWING_HEIGHT_MAX", "10"))
# [BOTTOM-LOW5 2026-06-13 ★친구님 지시] 바닥 정의: 0=현행(2일 전 국지 V저점) / N(≥2)=최근 N일 최저 지지선.
#   친구님 SR사이클 검증: 대장주 7일바퀴=중앙 9일·바닥주기, 진짜 바닥=5일최저. 백테(1년): 5일최저 승률49.5%·중앙~0
#   (현행 2일국지 평균↑이나 중앙-1.0%·승률46%=불안정). 선별필터(강매수세/천정여유/깊은눌림)는 다 악화→미적용.
#   롤백 setx SWING_BOTTOM_LOOKBACK 0.
SWING_BOTTOM_LOOKBACK = int(os.environ.get("SWING_BOTTOM_LOOKBACK", "0"))
# [HIGHER-LOW 2026-06-14 ★친구님] 당일 저가 > 전일 저가 = 저점 높임(돌아선 증거). 백테 +0.84%p(평균 +1.24→+2.08%, 승률·큰손실↑).
#   친구님 의도 "바닥 0 안 찍어도 오름세 확인하고 사기" 구현. 돌파는 백테 역효과(과열)라 제외. 롤백 setx SWING_HIGHER_LOW NO.
SWING_HIGHER_LOW = os.environ.get("SWING_HIGHER_LOW", "NO").strip().upper() == "YES"
# [SMART-EXIT B3 2026-06-14 ★친구님] 테마대장주 진입 + 조기매도(거래대금급감/5일선2일이탈) + 연장(종가>5일선).
#   백테(테마대장 964건 소급): 평균 +1.03→+2.10% · 큰손실 21→18% · 대박 6→8% = 수익↑+큰손실↓ 둘다.
#   ①오래들기=연장완화 ②먼저도망=조기매도. 롤백 setx 각 NO. ⚠소급근사라 실전데이터로 다듬을것.
SWING_THEME_LEADER_ONLY = os.environ.get("SWING_THEME_LEADER_ONLY", "NO").strip().upper() == "YES"
SWING_SMART_EXIT  = os.environ.get("SWING_SMART_EXIT", "NO").strip().upper() == "YES"
SWING_VOL_DROP    = float(os.environ.get("SWING_VOL_DROP", "0.4"))   # 어제 거래대금 < 직전3일평균×이값 = 급감
SWING_MA_DAYS     = int(os.environ.get("SWING_MA_DAYS", "5"))        # 5일선
SWING_MAX_HOLD    = int(os.environ.get("SWING_MAX_HOLD", "10"))      # 연장 최대 보유일
# [INTRADAY 2026-06-14 ★친구님] 14:57 1회 = 너무 늦음(저점후 2-3% 타이밍 한참 지남) → 장중 실시간 진입.
#   장중 5분마다 감시: 저점후 2~5% 반등(당일저가 대비) + 바닥 안찍음(당일저가>5일최저+α) + 돈실림(저점후 양봉대금≥50%).
#   Higher Low(2일,느림) 대체. 기본 OFF(현행 14:57 유지). 그림자=SWING_LIVE=NO면 실전과 동일기록·돈만 안나감.
SWING_INTRADAY      = os.environ.get("SWING_INTRADAY_ENABLE", "NO").strip().upper() == "YES"
SWING_REBOUND_MIN   = float(os.environ.get("SWING_REBOUND_MIN", "2"))   # 저점 후 반등 하한%
SWING_REBOUND_MAX   = float(os.environ.get("SWING_REBOUND_MAX", "5"))   # 저점 후 반등 상한%(넘으면 늦음)
SWING_DLOW_MIN      = float(os.environ.get("SWING_DLOW_MIN", "2"))      # 당일저가가 5일최저보다 이값%↑ 위(바닥 안찍음)
SWING_MONEYFLOW_MIN = float(os.environ.get("SWING_MONEYFLOW_MIN", "0.5"))  # 저점후 양봉(오를때) 거래대금 비중 하한
_THEME_STR_FILE   = Path(r"C:\stock_bot\data\theme\theme_strength.csv")
_THEME_LEADER_CACHE = {"date": None, "set": None}

def _load_theme_leaders():
    """theme_strength leader_code(테마대장주) set. 최신일. 실패/없음 → None(필터 무력=현행 유지)."""
    today = datetime.now().strftime("%Y%m%d")
    if _THEME_LEADER_CACHE["date"] == today:
        return _THEME_LEADER_CACHE["set"]
    s = set()
    try:
        with io.open(_THEME_STR_FILE, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
        latest = max((r.get("date", "") for r in rows), default="")
        for r in rows:
            if r.get("date", "") == latest:
                c = str(r.get("leader_code", "")).strip().zfill(6)
                if c and c != "000000":
                    s.add(c)
        if not s:
            s = None
    except Exception:
        s = None
    _THEME_LEADER_CACHE["date"] = today
    _THEME_LEADER_CACHE["set"] = s
    return s
# [B-TRACK 2026-06-17 ★친구님] B플랜 = A(5일지지선 눌림) 밖에서 '며칠 횡보(압축) 대장'을 선점 → 며칠보유 스윙.
#   백테(1년·깨끗한 per-code 루프) 4285건: 5일보유 +0.90% / 점수 상위10% 3일보유 +1.04%·승54%·최대낙폭 -2.7%
#   (점수 올릴수록 수익↑·승률↑·위험↓ = 단조개선 = 점수 작동). 검증식: pullback_btrack_swing_v2.py.
#   기존 '바닥반등 스윙'과 완전 별도 후보경로(독립). 기본 OFF=현행 100%. SWING_LIVE=NO면 모의기록(나중 채택용 데이터 축적).
#   롤백: setx SWING_BTRACK_ENABLE NO.
SWING_BTRACK_ENABLE    = os.environ.get("SWING_BTRACK_ENABLE", "NO").strip().upper() == "YES"
SWING_BTRACK_MIN_SCORE = float(os.environ.get("SWING_BTRACK_MIN_SCORE", "26"))   # 선별 문턱(백테 상위tier≈26+). 낮추면 후보多.
SWING_CONV60_BONUS     = float(os.environ.get("SWING_CONV60_BONUS", "8"))        # [7/6 친구님 조건2] 일봉 5/20/60 수렴+60일선 우상향 종목 가점. 0=끔
SWING_BTRACK_VAL_EOK   = float(os.environ.get("SWING_BTRACK_VAL_EOK", "50"))     # 당일대금 최소(억) — 대장 거름.
SWING_BTRACK_COIL_CR   = float(os.environ.get("SWING_BTRACK_COIL_CR", "0.06"))   # 5일 종가 (max-min)/평균 < = 횡보(압축)
SWING_BTRACK_COIL_DR   = float(os.environ.get("SWING_BTRACK_COIL_DR", "0.045"))  # 5일 일중(고-저)/종가 평균 < = 저변동
SWING_BTRACK_NEARHIGH  = float(os.environ.get("SWING_BTRACK_NEARHIGH", "0.93"))  # 현재가/10일고점 >= = 안빠짐(고점근처)
SWING_BTRACK_STOP_PCT  = float(os.environ.get("SWING_BTRACK_STOP_PCT", "3.0"))   # 보호손절 % (백테 최대낙폭 -2.7%)


_THEME_MEMB_FILE = r"C:\stock_bot\data\theme\theme_membership_naver.csv"
_THEME_MEMB_CACHE = {"date": "", "map": None}


def _load_theme_membership():
    """code -> theme_name (naver 스냅). 백테와 동일 소스. 실패 → None."""
    today = datetime.now().strftime("%Y%m%d")
    if _THEME_MEMB_CACHE["date"] == today:
        return _THEME_MEMB_CACHE["map"]
    mp = {}
    try:
        with io.open(_THEME_MEMB_FILE, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                c = str(r.get("code", "")).strip().zfill(6)
                th = (r.get("theme_name", "") or "").strip()
                if c and th and c not in mp:
                    mp[c] = th
        if not mp:
            mp = None
    except Exception:
        mp = None
    _THEME_MEMB_CACHE["date"] = today
    _THEME_MEMB_CACHE["map"] = mp
    return mp


def _btrack_theme_vtop(intra, series, topn=3):
    """테마내 당일 거래대금 top-N 코드 set (백테 vrank_t<=3 = '테마대장' 유니버스 재현).
       당일 v_t로 랭킹(분봉없으면 어제 EOD대금 폴백). membership 없으면 None(=폴백)."""
    memb = _load_theme_membership()
    if not memb:
        return None
    theme_vols = defaultdict(list)
    seen = set()
    for code, ia in intra.items():
        th = memb.get(code)
        if th:
            theme_vols[th].append((ia[3], code)); seen.add(code)
    # 분봉 없는 멤버는 어제 EOD 대금(백만→원)으로 보강(테마 랭킹 완성도)
    for code, th in memb.items():
        if code in seen:
            continue
        rows = series.get(code)
        if rows and th:
            theme_vols[th].append((rows[-1][5] * 1e6, code))
    vtop = set()
    for th, lst in theme_vols.items():
        lst.sort(reverse=True)
        for _v, c in lst[:topn]:
            vtop.add(c)
    return vtop


def _btrack_coil_scan(series, intra, held_codes):
    """[B플랜] 며칠 횡보(압축) 대장 선점 후보. 검증식(swing_v2) 그대로 라이브 적용.
       반환: [(bscore, code, px, nearhigh_gap%, detail)] 점수 내림차순. 실패/없음 → []."""
    out = []
    try:
        leaders = _btrack_theme_vtop(intra, series, 3)   # 테마내 거래대금 top3 (백테 유니버스)
        if leaders is None:
            leaders = _load_theme_leaders()              # 폴백: theme_strength 단일대장(None=무력)
        m5 = []                                       # 시장 5일수익(중앙값) = RS 기준(백테 idx 프록시)
        for _c, rws in series.items():
            if len(rws) >= 6 and rws[-6][4] > 0:
                m5.append(rws[-1][4] / rws[-6][4] - 1.0)
        mkt5 = sorted(m5)[len(m5) // 2] if m5 else 0.0
        for code, rows in series.items():
            if code in held_codes or len(rows) < 11:
                continue
            ia = intra.get(code)
            if not ia:
                continue
            o_t, l_t, c_t, v_t, _ts, _um, _dm, _lt = ia
            if not (c_t > 0):
                continue
            if leaders is not None and code not in leaders:
                continue                              # 테마대장만(명단 없으면 통과=폴백)
            if v_t < SWING_BTRACK_VAL_EOK * 1e8:      # 당일대금(원) 하한
                continue
            closes = [r[4] for r in rows]; highs = [r[2] for r in rows]; lows = [r[3] for r in rows]
            # 며칠 횡보(압축): 최근4일(어제~) 종가 + 오늘 현재가 = 5점 좁은범위
            c5 = closes[-4:] + [c_t]; c5mean = sum(c5) / len(c5)
            if c5mean <= 0:
                continue
            coil = (max(c5) - min(c5)) / c5mean
            dr = [(highs[i] - lows[i]) / closes[i] for i in range(-5, 0) if closes[i] > 0]
            dayrng = (sum(dr) / len(dr)) if dr else 1.0
            high10 = max(highs[-9:] + [c_t])
            if not (coil < SWING_BTRACK_COIL_CR and dayrng < SWING_BTRACK_COIL_DR
                    and high10 > 0 and c_t / high10 >= SWING_BTRACK_NEARHIGH):
                continue
            if rows[-6][4] <= 0:
                continue
            rs5 = ((rows[-1][4] / rows[-6][4] - 1.0) - mkt5) * 100.0   # RS_5D(어제기준, 시장중앙 대비)
            if rs5 <= 0:
                continue
            if min(lows[-3:] + [l_t]) < min(lows[-6:-3]):             # Higher Low(최근3일 저점 안붕괴)
                continue
            if rows[-4][4] > 0 and (c_t / rows[-4][4] - 1) > 0.20:    # 3일 급등 추격 제외
                continue
            if rows[-1][4] > 0 and (c_t / rows[-1][4] - 1) >= 0.15:   # 당일 급등 제외
                continue
            # ── 검증식 점수(swing_v2와 동일 골격, 대장성=거래대금 tier 프록시) ──
            sc = (15 if rs5 >= 7 else 11 if rs5 >= 5 else 7 if rs5 >= 3 else 3)
            sc += (10 if coil < 0.03 else 6 if coil < 0.045 else 3)
            veok = v_t / 1e8
            sc += (8 if veok >= 1000 else 5 if veok >= 500 else 3 if veok >= 100 else 0)
            y_val = rows[-1][5] * 1e6                                  # 어제대금(백만→원)
            if y_val > 0 and v_t > y_val * 1.2: sc += 6
            elif y_val > 0 and v_t > y_val: sc += 3
            if c_t / high10 >= 0.98: sc += 4
            if SWING_CONV60_BONUS:                    # [7/6 친구님 조건2] 일봉 5/20/60 수렴+60일선 우상향이면 가점(코스닥 백테 fwd3d +2.2%)
                try:
                    import daily_conv60 as _DC
                    if _DC.is_conv60(code): sc += SWING_CONV60_BONUS
                except Exception:
                    pass
            out.append((round(sc, 1), code, c_t, round((c_t / high10 - 1) * 100, 1),
                        {"rs5": round(rs5, 1), "coil": round(coil * 100, 1),
                         "veok": round(veok, 0), "nearhigh": round(c_t / high10, 3)}))
        out.sort(key=lambda x: x[0], reverse=True)
    except Exception as _e:
        log(f"[BTRACK] 스캔 실패({_e}) → B플랜 건너뜀")
        return []
    return out


# [ANCHOR 2026-06-13 친구님] 코스피 앵커 상대강도로 후보 정렬 살짝 기울임(소프트). 후보가 같은테마 앵커보다 강하면 우대.
#   백테 4일보유 +0.55%p. 앵커없는테마=0(무시). 기본 OFF. 롤백 setx SWING_ANCHOR_ENABLE NO.
SWING_ANCHOR_ENABLE = os.environ.get("SWING_ANCHOR_ENABLE", "NO").strip().upper() == "YES"

# [LOG-ENC 2026-06-13] cp949 콘솔에서 — 등 특수문자 print가 UnicodeEncodeError로
#   프로세스 전체를 죽임(주말 모의시험서 실증) → stdout을 replace 모드로.
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    try:
        with io.open(LOGF, "a", encoding="utf-8-sig") as f:
            f.write(line + "\n")
    except OSError:
        pass

def load_json(p):
    if p.exists() and p.stat().st_size > 1:
        try:
            with io.open(p, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            log(f"[WARN] {p.name} 읽기실패 {e}")
    return {}

def save_json(p, data):
    tmp = str(p) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, str(p))

def _shadow_csv_append(rec):
    """장중 그림자 진입을 표(csv)에 한 줄 — 실전과 동일정보. 채점은 mode_manage(shadow)가 exit/ret 채움."""
    try:
        SHADOW_CSV.parent.mkdir(parents=True, exist_ok=True)
        new = (not SHADOW_CSV.exists()) or SHADOW_CSV.stat().st_size < 5
        with io.open(SHADOW_CSV, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "entry_time", "code", "entry_price", "qty", "bottom",
                            "height", "rebound", "moneyflow", "value_eok",
                            "status", "exit_date", "exit_price", "ret_pct", "reason"])
            w.writerow([rec["entry_date"], rec["entry_time"], rec["code"], rec["entry_price"],
                        rec["qty"], rec["bottom"], rec["height"], rec["rebound"],
                        rec["moneyflow"], rec.get("value_eok", 0), "OPEN", "", "", "", ""])
    except Exception as e:
        log(f"[ISHADOW] csv 기록실패 {e}")

def _shadow_csv_close(code, exit_date, exit_price, ret_pct, reason):
    """그림자 청산 시 csv의 해당 OPEN행을 CLOSED로 갱신(전체 재작성)."""
    try:
        if not SHADOW_CSV.exists(): return
        rows = list(csv.reader(io.open(SHADOW_CSV, encoding="utf-8-sig")))
        if not rows: return
        hdr, body = rows[0], rows[1:]
        for r in body:
            if len(r) >= 11 and r[2] == code and r[10] == "OPEN":
                r[10] = "CLOSED"; r[11] = exit_date; r[12] = f"{exit_price:.0f}"
                r[13] = f"{ret_pct:.2f}"; r[14] = reason
                break
        with io.open(SHADOW_CSV, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(hdr); w.writerows(body)
    except Exception as e:
        log(f"[ISHADOW] csv 청산갱신 실패 {e}")

def load_eod():
    series = defaultdict(list)
    with io.open(EOD, encoding="utf-8-sig", errors="replace") as fp:
        for r in csv.DictReader(fp):
            if r.get("market") != "KOSDAQ": continue
            d = r["date"]
            if d < "20260301": continue
            try:
                o = float(r["open"] or 0); h = float(r["high"] or 0)
                l = float(r["low"] or 0); c = float(r["close"] or 0)
                v = float(r["value"] or 0)
            except (TypeError, ValueError):
                continue
            if o > 0 and c > 0 and l > 0:
                series[r["code"]].append((d, o, h, l, c, v))
    for c in series: series[c].sort()
    return series

def today_intraday():
    """당일 분봉 종목별 [시가, 당일저가, 현재가, 누적대금, 마지막ts, 저점후양봉대금, 저점후음봉대금, 저가시각].
    저점후 돈흐름(up_m/dn_m)=장중진입 '돈 실림' 판정용(SWING_INTRADAY). value칸(c[7])=수집 거래대금(원)."""
    today = datetime.now().strftime("%Y%m%d")
    bars = defaultdict(list)
    if not P1M.exists(): return {}, today
    with io.open(P1M, encoding="utf-8-sig", errors="replace") as fp:
        rd = csv.reader(fp); next(rd)
        for c in rd:
            if not c[1].startswith(today) or c[0] in ("U001", "U201"): continue
            try:
                o = float(c[2]); l = float(c[4]); cl = float(c[5]); v = float(c[7] or 0)
            except (ValueError, IndexError):
                continue
            bars[c[0]].append((c[1], o, l, cl, v))
    agg = {}
    for code, bl in bars.items():
        if not bl: continue
        bl.sort()
        o_t = bl[0][1]; c_t = bl[-1][3]; v_t = sum(b[4] for b in bl); last_ts = bl[-1][0]
        li = min(range(len(bl)), key=lambda i: bl[i][2])      # 당일 저가 분봉 위치
        l_t = bl[li][2]; after = bl[li:]                       # 저점(포함) 이후
        up_m = sum(b[4] for b in after if b[3] >= b[1])        # 양봉(오를때) 거래대금
        dn_m = sum(b[4] for b in after if b[3] < b[1])         # 음봉(내릴때) 거래대금
        agg[code] = [o_t, l_t, c_t, v_t, last_ts, up_m, dn_m, bl[li][0]]
    return agg, today

def broker_order(code, qty, side, lg_tag):
    """주문 (검증된 broker_client.send_order_real 경로, 최유리 06=집안 표준). SWING_LIVE=NO면 모의.
    order_type: 1=매수 / 2=매도. idempotency_key 필수(uuid)."""
    if not SWING_LIVE:
        log(f"[{lg_tag}][PAPER] {side} {code} x{qty} (모의 — SWING_LIVE=NO)")
        return True
    try:
        import uuid
        sys.path.insert(0, r"C:\stock_bot\RUN")
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            log(f"[{lg_tag}] broker dead → 주문 불가"); return False
        bc = BrokerClient()
        account = os.environ.get("SWING_ACCOUNT", "").strip()
        if not account:
            try:
                ai = bc.account_info("ACCNO")
                accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
                if isinstance(accs, str): accs = [a for a in accs.split(";") if a]
                account = accs[0] if accs else ""
            except Exception as _ae:
                log(f"[{lg_tag}] 계좌조회 실패: {_ae}")
        if not account:
            log(f"[{lg_tag}] 계좌번호 없음 → 주문 불가 (setx SWING_ACCOUNT 계좌번호)"); return False
        order_type = 1 if side == "BUY" else 2
        r = bc.send_order_real(idempotency_key=f"swing_{side.lower()}_{code}_{uuid.uuid4()}",
                               account=account, code=code, qty=int(qty),
                               order_type=order_type, price=0, hoga_gb="06",
                               rqname=f"SWING_{side}_{code}", screen_no="9702")
        log(f"[{lg_tag}][LIVE] {side} {code} x{qty} acct={account[:4]}** → {str(r)[:120]}")
        return str((r or {}).get("status", "")).upper() not in ("ERROR", "FAIL")
    except Exception as e:
        log(f"[{lg_tag}] 주문 실패: {e}")
        return False

def mode_pick(shadow=False):
    # [INTRADAY ★친구님 병행] shadow=True = 장중 그림자(실전 종가스윙과 분리·별도 ledger·돈 안나감). 동시 가능.
    intraday_on = SWING_INTRADAY or shadow          # 그림자는 항상 장중조건(저점후반등+바닥안찍음+돈실림)
    live_on = SWING_LIVE and not shadow             # 그림자는 항상 모의
    ledger_path = SHADOW_LEDGER if shadow else LEDGER
    tag = "ISHADOW" if shadow else "PICK"
    # [US-CRASH-GUARD 2026-06-14 ★친구님] 나스닥 -4%↓ 대폭락날 = 신규 스윙 진입 스킵.
    try:
        sys.path.insert(0, r"C:\stock_bot\RUN")
        from us_crash_guard import is_us_crash_day
        _blk, _why = is_us_crash_day()
        if _blk:
            log(f"[{tag}][US-CRASH-GUARD] {_why} → 스윙 신규 스킵"); return
    except Exception as _e:
        log(f"[{tag}][US-CRASH-GUARD] 체크실패({_e}) → 평소진행")
    series = load_eod()
    intra, today = today_intraday()
    ledger = load_json(ledger_path)
    if shadow:
        held_codes = {c for c, v in ledger.items() if isinstance(v, dict) and v.get("status") == "OPEN"}
    else:
        rt = load_json(RT_OPEN)
        held_codes = {c for c, v in rt.items() if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0}
        held_codes |= {c for c, v in ledger.items() if isinstance(v, dict) and v.get("status") == "OPEN"}
    open_swings = sum(1 for v in ledger.values() if isinstance(v, dict) and v.get("status") == "OPEN")
    if open_swings >= SWING_MAX_POS:
        log(f"[{tag}] 스윙 보유 {open_swings}/{SWING_MAX_POS} → 신규 없음"); return

    cands = []
    for code, rows in series.items():
        if code in held_codes: continue            # ★중복매수 금지(전략 불문)
        if len(rows) < 25: continue
        ia = intra.get(code)
        if not ia: continue
        o_t, l_t, c_t, v_t, _ts, up_m, dn_m, _lowts = ia
        # 바닥 정의: [BOTTOM-LOW5] env로 전환. 0=현행(2일 국지 V) / N≥2=최근 N일 최저 지지선(진짜 사이클 바닥).
        lows = [r[3] for r in rows]
        if SWING_BOTTOM_LOOKBACK >= 2:
            # 최근 N일(어제까지) 최저 = 진짜 지지선. 종가가 +7~10% = 반등 확인이라 별도 V검증 불요.
            if len(lows) < SWING_BOTTOM_LOOKBACK: continue
            bot = min(lows[-SWING_BOTTOM_LOOKBACK:])
        else:
            ib = len(rows) - 2          # 그저께(어제가 -1) — '2일 전' 국지 바닥
            if ib < 2: continue
            bot = lows[ib]
            if not (bot < min(lows[ib-2], lows[ib-1], lows[ib+1], l_t)): continue
        if bot <= 0: continue
        vals = [r[5] for r in rows]
        recent_big = sum(1 for j in range(max(0, len(rows) - 20), len(rows)) if vals[j] >= 100000)
        # [SMART-EXIT B3] 대장 정의: 테마대장주(켜짐) 또는 거래대금 대장(현행).
        if SWING_THEME_LEADER_ONLY:
            _tl = _load_theme_leaders()
            if _tl and code not in _tl: continue        # 테마대장주만 (명단없음→현행 폴백)
            elif _tl is None and recent_big < 2: continue
        else:
            if recent_big < 2: continue                  # 현행 거래대금 대장
        height = (c_t / bot - 1) * 100
        if not (HEIGHT_MIN <= height < HEIGHT_MAX): continue   # [HEIGHT-BAND] 기본 7~10
        # 매수세: 당일 양봉 + 당일 누적대금(원, 수집기준) > 전일 대금(백만→원 환산)
        #   ⚠수집대금은 과소집계 경향 → 이 조건은 보수적(진짜 증가만 통과)
        if not (c_t >= o_t and v_t > rows[-1][5] * 1_000_000): continue
        # [HIGHER-LOW] 당일 저가 > 전일 저가 = 저점 높임. 장중모드면 저점후반등(1일)로 대체하니 skip.
        if SWING_HIGHER_LOW and not intraday_on and l_t <= rows[-1][3]: continue
        _reb = (c_t / l_t - 1) * 100 if l_t > 0 else 0.0               # 저점 후 반등%(당일저가 대비 현재가)
        _mflow = (up_m / (up_m + dn_m)) if (up_m + dn_m) > 0 else 0.0  # 저점후 양봉(오를때) 거래대금 비중
        if intraday_on:
            # [INTRADAY ★친구님] 장중 실시간: 저점후 2~5% 반등 + 바닥 안찍음 + 돈 실림 = '돌아선 순간' 포착
            if not (SWING_REBOUND_MIN <= _reb <= SWING_REBOUND_MAX): continue   # 미반등/늦음(6%+) 제외
            if l_t <= bot * (1 + SWING_DLOW_MIN / 100.0): continue              # 당일저가>5일최저 지지선(바닥 안찍음)
            if _mflow < SWING_MONEYFLOW_MIN: continue                          # 오를때 돈 안실림=가짜반등 제외
        _pc = rows[-1][4]
        _cret = round((c_t / _pc - 1) * 100, 2) if _pc else 0.0   # 당일 등락(앵커 상대강도용)
        cands.append((v_t, code, c_t, bot, height, _cret, _reb, _mflow))
    # [B-TRACK ★친구님 2026-06-17] B플랜(며칠 횡보 대장 선점) 스캔 — 바닥반등과 완전 독립경로(종가모드만).
    btrack_pick = None
    if SWING_BTRACK_ENABLE and not intraday_on:
        bcands = _btrack_coil_scan(series, intra, held_codes)
        if bcands:
            log(f"[BTRACK] 횡보대장 후보 {len(bcands)}개 (최고 {bcands[0][0]}점, 문턱 {SWING_BTRACK_MIN_SCORE}) "
                f"상위: {', '.join(f'{b[1]}:{b[0]}' for b in bcands[:3])}")
            if bcands[0][0] >= SWING_BTRACK_MIN_SCORE:
                btrack_pick = bcands[0]
    if not cands and not btrack_pick:
        log(f"[{tag}] 오늘 후보 없음 (정상 — 주 3회꼴)"); return
    if btrack_pick:
        # B플랜: 강한 횡보 대장이 문턱 넘으면 우선(검증 알파). 보호손절=현재가 -STOP%.
        bsc, code, px, _nh, _det = btrack_pick
        v_t = int(_det["veok"] * 1e8); height = 0.0; _cret = 0.0; _reb = 0.0; _mflow = 0.0
        bot = round(px * (1.0 - SWING_BTRACK_STOP_PCT / 100.0))
        setup = "COIL"
        log(f"[BTRACK-COIL] ★B플랜 횡보선점 1등: {code} @{px:,.0f} 점수{bsc} "
            f"(RS5={_det['rs5']} 압축{_det['coil']}% 고점근처{_det['nearhigh']} 당일대금{_det['veok']:.0f}억, "
            f"손절 {bot:,.0f} -{SWING_BTRACK_STOP_PCT:.0f}%)")
    else:
        # [ANCHOR] 코스피 앵커 상대강도로 정렬 살짝 기울임(후보가 같은테마 앵커보다 강하면 우대). 기본 OFF.
        if SWING_ANCHOR_ENABLE:
            try:
                from anchor_bonus import load_anchor_ctx as _lac, anchor_bonus as _abf
                _ac, _at, _act = _lac()
                if _ac:
                    def _akey(x):
                        _b, _ = _abf(_act.get(x[1], []), x[5], _ac, _at, 10.0)
                        return x[0] * (1.0 + _b / 50.0)   # 거래대금 × (앵커보너스 최대 +20%)
                    cands.sort(key=_akey, reverse=True)
                    log("[ANCHOR] 스윙 후보 앵커 상대강도 반영 정렬")
                else:
                    cands.sort(reverse=True)
            except Exception as _ae:
                log(f"[ANCHOR] 실패({_ae}) → 거래대금 정렬"); cands.sort(reverse=True)
        else:
            cands.sort(reverse=True)
        v_t, code, px, bot, height, _cret, _reb, _mflow = cands[0]
        setup = "BOTTOM"
    qty = max(1, int(SWING_CAP_KRW // px))
    if qty * px > SWING_CAP_KRW * 1.05:
        qty = max(1, qty - 1)
    _mode = "장중" if intraday_on else ("횡보선점" if setup == "COIL" else "종가")
    _lbl = " [그림자]" if shadow else ("" if live_on else " [모의]")
    if setup == "COIL":
        log(f"[{tag}]{_lbl} ★B플랜 스윙(횡보선점) 1등: {code} @{px:,.0f} x{qty} "
            f"(손절 {bot:,.0f} -{SWING_BTRACK_STOP_PCT:.0f}%, 당일대금 {v_t/1e8:,.0f}억, {datetime.now():%H:%M})")
    else:
        log(f"[{tag}]{_lbl} ★스윙({_mode}) 1등: {code} @{px:,.0f} x{qty} "
            f"(바닥 {bot:,.0f} +{height:.1f}%, 저점후반등 +{_reb:.1f}%, 돈실림 {_mflow*100:.0f}%, "
            f"당일대금 {v_t/1e8:,.0f}억, {datetime.now():%H:%M}, 후보 {len(cands)})")
    # 실탄이면 broker 주문(실패시 기록 안함). 그림자/모의면 주문 없이 바로 기록 = 실전과 동일정보, 돈만 안나감.
    if live_on and not broker_order(code, qty, "BUY", "PICK"):
        return
    rec = {"code": code, "qty": qty, "entry_price": px, "bottom": bot,
           "entry_date": today, "held_days": 0, "status": "OPEN",
           "sell_due": "", "strategy": "SWING", "setup": setup,
           "height": round(height, 2), "rebound": round(_reb, 2),
           "moneyflow": round(_mflow, 3), "entry_mode": _mode,
           "entry_time": datetime.now().strftime("%H:%M:%S"),
           "value_eok": round(v_t / 1e8, 1),
           "shadow": shadow, "live": live_on, "ts": datetime.now().isoformat()}
    ledger[code] = rec
    save_json(ledger_path, ledger)
    if shadow:
        _shadow_csv_append(rec)        # 그림자 전용 표(실전과 동일 정보, 채점기가 4일후 성과 채움)
    if live_on:
        rt = load_json(RT_OPEN)
        rt[code] = {"qty": qty, "entry_price": px, "code": code, "strategy": "SWING",
                    "peak_price": px, "stop_price": bot, "_hard_stop_pct": 0.0,
                    "_swing": 1, "_chejan_ts": datetime.now().isoformat()}
        save_json(RT_OPEN, rt)

def mode_manage(shadow=False):
    ledger_path = SHADOW_LEDGER if shadow else LEDGER
    tag = "IMANAGE" if shadow else "MANAGE"
    ledger = load_json(ledger_path)
    intra, today = today_intraday()
    series = load_eod() if SWING_SMART_EXIT else {}   # [SMART-EXIT] 거래대금·5일선 계산용
    changed = False
    for code, p in ledger.items():
        if not isinstance(p, dict) or p.get("status") != "OPEN": continue
        if p.get("entry_date") == today: continue
        p["held_days"] = int(p.get("held_days", 0)) + 1
        ia = intra.get(code)
        close_t = ia[2] if ia else None
        reason = ""
        if SWING_SMART_EXIT and close_t is not None and len(series.get(code, [])) >= SWING_MA_DAYS + 1:
            # [SMART-EXIT B3] 죽으면 먼저(거래대금급감/5일선2일이탈) · 살면 연장(종가>5일선, 최대 SWING_MAX_HOLD일)
            rows = series[code]
            closes = [r[4] for r in rows]; vols = [r[5] for r in rows]
            ma = sum(closes[-SWING_MA_DAYS:]) / SWING_MA_DAYS           # 5일선(어제까지)
            v_y = vols[-1]                                              # 어제 거래대금(확정)
            v3 = sum(vols[-4:-1]) / 3 if len(vols) >= 4 else v_y        # 그제~3일전 평균
            below = int(p.get("below5", 0))
            below = below + 1 if close_t < ma else 0
            p["below5"] = below
            if close_t < float(p["bottom"]):
                reason = f"바닥이탈({close_t:,.0f}<{float(p['bottom']):,.0f})"
            elif v3 > 0 and v_y < v3 * SWING_VOL_DROP:
                reason = f"거래대금급감(어제 {v_y:,.0f}<직전3일평균 {v3:,.0f}×{SWING_VOL_DROP})"
            elif below >= 2:
                reason = f"5일선 2일이탈(종가 {close_t:,.0f}<5일선 {ma:,.0f})"
            elif p["held_days"] >= HOLD_DAYS and close_t > ma:
                reason = ""        # ★살아있음(종가>5일선) → 연장
            elif p["held_days"] >= HOLD_DAYS:
                reason = f"{HOLD_DAYS}일도달·5일선아래"
            if not reason and p["held_days"] >= SWING_MAX_HOLD:
                reason = f"최대보유 {SWING_MAX_HOLD}일"
        else:
            # 현행(4일 고정 + 바닥이탈)
            if close_t is not None and close_t < float(p["bottom"]):
                reason = f"바닥이탈(종가 {close_t:,.0f} < {float(p['bottom']):,.0f})"
            elif p["held_days"] >= HOLD_DAYS:
                reason = f"{HOLD_DAYS}거래일 도달"
        if reason:
            p["sell_due"] = reason
            log(f"[{tag}] {code} → 내일 매도 예약: {reason}")
        else:
            log(f"[{tag}] {code} 보유 {p['held_days']}일째 유지 (종가 {close_t if close_t else '?'}, 연장중)")
        changed = True
    if changed: save_json(ledger_path, ledger)

def mode_sell(shadow=False):
    ledger_path = SHADOW_LEDGER if shadow else LEDGER
    tag = "ISELL" if shadow else "SELL"
    ledger = load_json(ledger_path)
    intra, today = today_intraday()      # 그림자 모의매도가(현재가)용
    changed = False
    for code, p in ledger.items():
        if not isinstance(p, dict) or p.get("status") != "OPEN" or not p.get("sell_due"): continue
        if shadow:
            # 그림자: 돈 안나감 — 현재가로 모의매도 + 수익률 기록(csv 갱신)
            ia = intra.get(code)
            exit_px = float(ia[2]) if ia else float(p["entry_price"])
            ret = (exit_px / float(p["entry_price"]) - 1) * 100
            p["status"] = "CLOSED"; p["exit_date"] = today; p["exit_price"] = exit_px
            p["exit_reason"] = p["sell_due"]; p["ret_pct"] = round(ret, 2)
            _shadow_csv_close(code, today, exit_px, ret, p["sell_due"])
            log(f"[ISELL][그림자] {code} 모의매도 @{exit_px:,.0f} = {ret:+.2f}% ({p['sell_due']})")
            changed = True
        elif broker_order(code, int(p["qty"]), "SELL", "SELL"):
            p["status"] = "CLOSED"; p["exit_date"] = datetime.now().strftime("%Y%m%d")
            p["exit_reason"] = p["sell_due"]
            log(f"[SELL] {code} x{p['qty']} 매도 ({p['sell_due']})")
            if SWING_LIVE:
                rt = load_json(RT_OPEN)
                if code in rt and rt[code].get("strategy") == "SWING":
                    del rt[code]; save_json(RT_OPEN, rt)
            changed = True
    if changed: save_json(ledger_path, ledger)
    else: log(f"[{tag}] 매도 예약분 없음")

def btrack_dryrun():
    """[검증용] B플랜 횡보대장 스캔만 — 주문/기록 0, 후보만 출력. 장중 아무때나 안전(READ-ONLY)."""
    series = load_eod(); intra, today = today_intraday()
    rt = load_json(RT_OPEN); ledger = load_json(LEDGER)
    held = {c for c, v in rt.items() if isinstance(v, dict) and float(v.get("qty", 0) or 0) > 0}
    held |= {c for c, v in ledger.items() if isinstance(v, dict) and v.get("status") == "OPEN"}
    log(f"[BTRACK-DRYRUN] {today} ENABLE={SWING_BTRACK_ENABLE} 문턱={SWING_BTRACK_MIN_SCORE} "
        f"대금하한={SWING_BTRACK_VAL_EOK}억 / eod종목 {len(series)}, 당일분봉 {len(intra)}, 보유 {len(held)}")
    bcands = _btrack_coil_scan(series, intra, held)
    if not bcands:
        log("[BTRACK-DRYRUN] 후보 0개 (오늘 횡보대장 신호 없음 또는 분봉 미수집)"); return
    log(f"[BTRACK-DRYRUN] 후보 {len(bcands)}개 — 상위 10:")
    for sc, code, px, nh, det in bcands[:10]:
        mark = "★문턱통과" if sc >= SWING_BTRACK_MIN_SCORE else ""
        log(f"   {code} @{px:,.0f} 점수{sc} {mark} (RS5={det['rs5']} 압축{det['coil']}% "
            f"고점근처{det['nearhigh']} 당일대금{det['veok']:.0f}억)")
    log(f"[BTRACK-DRYRUN] → 실거래라면 1등 {bcands[0][1]} (점수{bcands[0][0]}) "
        f"{'선정' if bcands[0][0] >= SWING_BTRACK_MIN_SCORE else '문턱미달=미선정'}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "manage"
    log(f"=== swing_manager {mode} (LIVE={SWING_LIVE}, INTRADAY={SWING_INTRADAY}, BTRACK={SWING_BTRACK_ENABLE}, CAP={SWING_CAP_KRW:,}) ===")
    {"pick": mode_pick, "manage": mode_manage, "sell": mode_sell,
     "btrack_dryrun": btrack_dryrun,                        # B플랜 스캔 검증(주문0·기록0)
     "intraday_shadow": lambda: mode_pick(shadow=True),     # 장중 그림자 진입(5분마다)
     "intraday_manage": lambda: mode_manage(shadow=True),   # 그림자 보유관리(15:05)
     "intraday_sell":   lambda: mode_sell(shadow=True),     # 그림자 모의매도(09:01)
     }[mode]()
