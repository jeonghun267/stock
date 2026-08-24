# -*- coding: utf-8 -*-
"""🎯 통합 후보 선별기 — 주문0·TR0·SetRealReg0 [2026-07-20 친구님 "단일 종합점수 X, 4개 점수 분리"]

목적: micro_rank_engine_v1.py가 만든 120종목 실시간 랭킹 위에서, 종목마다
  attention(관심도)·valley(저점반등형)·breakout(돌파형)·ma_pullback(이평눌림형)
  4개 점수를 각각 유지하는 2차 선별 레이어. "관심도"는 슬롯경쟁용, 실제 전략 연결은
  나머지 3개 전략점수로 결정 — 하나의 점수로 뭉개지 않는다(친구님 명시 지시).

★설계 확정 이력(대화 중 결정):
  · 깔때기(TOP40→20→10→5 단계적 탈락) 전면 폐기 — 120종목 전부 매틱 전지표 계산 후
    "단 한 번" 정렬. TOP5/10/20/40은 서로 다른 선별단계가 아니라 같은 정렬의 다른 길이 뷰.
    (이유: 초반 단계 기준 하나로 조기탈락하면 후반 단계 지표가 평가 기회조차 못 받는
    구조적 편향이 생김 — 120종목 전부 계산해도 가볍다는 게 이미 증명됐으니 걸러낼 이유 없음)
  · L0/L1 승격·강등, 정밀계산 대상 제한 전부 제거 — micro_rank_engine과 달리 등급/순위
    안정화용 히스테리시스를 이 엔진에는 두지 않는다(친구님 명시 지시, 단순구조 우선).
  · ma_pullback_score 필요한 "정배열" 정보는 새 데이터소스 없이 기존 캐시
    (C:\\stock_bot\\data\\돈맥_추세배지.json, money_flow_board_v1.py가 이미 쓰는 일1회 TR0 캐시) 재사용.
  · reasons/risks는 AI/LLM 호출 없이 임계값 기반 규칙 템플릿 문자열로만 생성(결정론적).
  · [2026-07-20 밤 추가] 테마 로테이션 = 같은 테마 종목 평균 attention_score가 높으면 소폭 보너스
    (기계적 집계, 점수 반영). 리더-팔로워 = ★점수에 전혀 반영 안 함, 순수 관측·로그만
    (메모리 "승자vs패자 비교 금지" 규칙 — 전수백테 검증 전엔 신호로 안 씀).

입력(읽기전용 3개, 전부 TR 0):
  · live_micro_snapshot.json — 가격(cur)·호가총잔량(ask_tot/bid_tot) 자체 롤링버퍼용
    (micro_rank_board.json 공개 스키마엔 cur/ask_tot/bid_tot이 없어서 직접 읽음 —
     micro_rank_engine_v1.py는 무수정 유지가 조건이라 그쪽 출력필드를 늘리지 않음)
  · micro_rank_board.json — micro_rank_engine의 rank·score·grade·che·che_accel·
    money_30s·money_accel·imbalance·imbalance_delta_10s·name 재사용(재계산 없음)
  · 돈맥_추세배지.json — 일봉 정배열 배지(일1회 갱신, ma_pullback_score 전용)
  · theme_membership_naver.csv — 종목-테마 매핑(일1회 갱신, theme_map_v1.py가 이미 만드는 기존 캐시 재사용)

출력: integrated_candidate_board.json(attention_rank 전체·top5/10/20/40 뷰·전략별 top10·
  outlier_alerts) · integrated_candidate_history.csv(이벤트만) · LOG

리허설 주입구(env, 미설정시 실서비스 경로 기본값):
  ICE_SNAP·ICE_BOARD·ICE_TREND·ICE_OUT·ICE_LOG·ICE_HIST
  ICE_POLL(1.0)·ICE_BUFFER_MIN(10)·ICE_VOL_WINDOW(300)·ICE_MIN_VALID(20)
  ICE_OUTLIER_Z(3.0)·ICE_OUTLIER_BONUS(10)
  ICE_W_ATT_SCORE(50)·ICE_W_ATT_VEL(30)·ICE_W_ATT_RS(20)
  ICE_W_VAL_REBOUND(50)·ICE_W_VAL_VOL(30)·ICE_W_VAL_CHEACCEL(20)
  ICE_W_BRK_COMPRESS(40)·ICE_W_BRK_RS(30)·ICE_W_BRK_MACCEL(30)
  ICE_W_MAP_TREND(60)·ICE_W_MAP_REBOUND(40)   — 전부 이번 작업 미튜닝(기본값 그대로)
"""
import os
import csv
import json
import time
from bisect import bisect_left, bisect_right
from collections import deque
from datetime import datetime
from pathlib import Path

SNAP  = Path(os.environ.get("ICE_SNAP")  or r"C:\stock_bot\IPC\live_micro_snapshot.json")
BOARD = Path(os.environ.get("ICE_BOARD") or r"C:\stock_bot\data\micro_rank_board.json")
TREND = Path(os.environ.get("ICE_TREND") or r"C:\stock_bot\data\돈맥_추세배지.json")
THEME_MEMB = Path(os.environ.get("ICE_THEME_MEMB") or r"C:\stock_bot\data\theme\theme_membership_naver.csv")
OUT   = Path(os.environ.get("ICE_OUT")   or r"C:\stock_bot\data\integrated_candidate_board.json")
LOG   = Path(os.environ.get("ICE_LOG")   or r"C:\stock_bot\data\LOG\integrated_candidate_engine.log")
HIST  = Path(os.environ.get("ICE_HIST")  or r"C:\stock_bot\data\integrated_candidate_history.csv")

POLL_SEC   = float(os.environ.get("ICE_POLL", "1.0"))
STOP_HM    = os.environ.get("ICE_STOP_HM", "1535").zfill(4)
BUFFER_MIN = float(os.environ.get("ICE_BUFFER_MIN", "10"))
VOL_WINDOW = float(os.environ.get("ICE_VOL_WINDOW", "300"))
MIN_VALID  = int(os.environ.get("ICE_MIN_VALID", "20"))
OUTLIER_Z      = float(os.environ.get("ICE_OUTLIER_Z", "3.0"))
OUTLIER_BONUS  = float(os.environ.get("ICE_OUTLIER_BONUS", "10"))

W_ATT_SCORE = float(os.environ.get("ICE_W_ATT_SCORE", "50"))
W_ATT_VEL   = float(os.environ.get("ICE_W_ATT_VEL", "30"))
W_ATT_RS    = float(os.environ.get("ICE_W_ATT_RS", "20"))

W_VAL_REBOUND  = float(os.environ.get("ICE_W_VAL_REBOUND", "50"))
W_VAL_VOL      = float(os.environ.get("ICE_W_VAL_VOL", "30"))
W_VAL_CHEACCEL = float(os.environ.get("ICE_W_VAL_CHEACCEL", "20"))

W_BRK_COMPRESS = float(os.environ.get("ICE_W_BRK_COMPRESS", "40"))
W_BRK_RS       = float(os.environ.get("ICE_W_BRK_RS", "30"))
W_BRK_MACCEL   = float(os.environ.get("ICE_W_BRK_MACCEL", "30"))

W_MAP_TREND    = float(os.environ.get("ICE_W_MAP_TREND", "60"))
W_MAP_REBOUND  = float(os.environ.get("ICE_W_MAP_REBOUND", "40"))

# ★[2026-07-20 밤 친구님 "테마 로테이션·리더팔로워도 마저 만들어줘"] 추가 2건.
#   테마 로테이션: 같은 테마 종목들의 attention_score 평균이 높으면 "테마 전체 자금유입"으로 보고
#   소폭 보너스(THEME_BONUS_MAX 상한) — 기계적 집계라 리스크 낮음, 곧바로 점수에 반영.
#   리더-팔로워: 메모리 규칙(승자vs패자 비교 금지 — 진입시점 기준 전수백테 없이 사후관찰만으로
#   결론내면 버그를 전략으로 착각할 위험)에 따라 ★점수에는 전혀 반영하지 않고 관측/기록만 한다.
#   leader_lag_sec는 순수 로그용 — attention_score·전략점수 어디에도 안 들어감.
THEME_HOT_TH    = float(os.environ.get("ICE_THEME_HOT_TH", "70"))   # 이 이상이면 "핫"으로 간주(리더/팔로워 판정 기준)
THEME_BONUS_MAX = float(os.environ.get("ICE_THEME_BONUS_MAX", "10"))  # attention_score 보너스 상한(outlier와 동급)

_che_history = {}  # code -> deque[(epoch, che)] — 이상치(자기 시계열) z-score 전용, board pass-through와 별개
_code_hot_since = {}   # code -> epoch(attention_score가 THEME_HOT_TH를 넘긴 시각). 안 넘으면 키 삭제.
_theme_leader_now = {}  # theme_name -> 현재 리더 code (로그용)

_PUBLIC_FIELDS = (
    "rank", "code", "name", "attention_score", "valley_score", "breakout_score",
    "ma_pullback_score", "primary_strategy", "confidence", "reasons", "risks",
    "grade", "score", "che", "che_accel", "money_30s", "money_accel",
    "imbalance", "rank_velocity", "volatility_pct", "bottom_rebound_pct",
    "rs_che", "outlier_flag", "trend45", "depth_compress_pct", "snapshot_age_sec",
    "theme_name", "theme_flow_score", "is_theme_leader", "leader_lag_sec",
    # ── [2026-07-21 신규 자금유입 — 친구님 지시] micro_rank_board가 이미 계산해 놓은 값을
    #    그대로 통과만 시킨다(재계산 없음, row=dict(it)가 이미 전부 복사해옴 — 여기선
    #    출력필드 화이트리스트에 추가만 하면 됨). 기존 필드 전부 무변경.
    "money_10s_now", "money_10s_prev", "money_30s_now", "money_30s_prev",
    "money_60s_now", "money_60s_prev", "money_180s_now", "money_180s_prev",
    "money_add_10s", "money_add_30s", "money_add_60s", "money_add_180s",
    "money_ratio_10s", "money_ratio_30s", "money_ratio_60s",
    "money_speed_10s", "money_speed_30s",
    "money_accel_10s", "money_accel_30s", "money_accel_pct_30s",
    "che_raw", "che_delta_5s", "che_accel_10s", "che_accel_30s",
    "money_flow_score", "money_flow_rank", "money_flow_state",
    "money_flow_since", "money_flow_reasons", "money_flow_data_quality",
)


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    # 여러 실행 인스턴스가 같은 .tmp를 잡지 않도록 프로세스별 임시파일을 쓴다.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    try:
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except OSError as e:
                # Windows에서 독자가 대상 JSON을 잠깐 열고 있으면 교체가 거부될 수 있다.
                if getattr(e, "winerror", None) not in (5, 32) or attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


_HIST_HEADER = ["ts", "event", "code", "name", "detail"]


def _hist_write(event, code, name, detail=""):
    try:
        HIST.parent.mkdir(parents=True, exist_ok=True)
        new = not HIST.exists()
        with HIST.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(_HIST_HEADER)
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, code, name, detail])
    except Exception as e:
        _log(f"[HIST] 기록 실패(무시): {e}")


_trend_codes = set()
_trend_mtime = None


def _load_trend45():
    global _trend_codes, _trend_mtime
    try:
        mt = TREND.stat().st_mtime
    except Exception:
        return
    if mt == _trend_mtime:
        return
    try:
        d = json.loads(TREND.read_text(encoding="utf-8-sig"))
        _trend_codes = {str(c).zfill(6) for c in (d.get("codes") or [])}
        _trend_mtime = mt
    except Exception as e:
        _log(f"[TREND] 배지 캐시 읽기 실패(직전 값 유지): {e}")


_theme_of = {}        # code -> theme_name(첫 소속만, 다중소속시 CSV상 첫 행)
_theme_members = {}   # theme_name -> [code, ...]
_theme_mtime = None


def _load_theme_map():
    global _theme_of, _theme_members, _theme_mtime
    try:
        mt = THEME_MEMB.stat().st_mtime
    except Exception:
        return
    if mt == _theme_mtime:
        return
    try:
        theme_of, members = {}, {}
        with THEME_MEMB.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                code = str(row.get("code", "")).zfill(6)
                name = row.get("theme_name", "")
                if not code or not name:
                    continue
                theme_of.setdefault(code, name)  # 첫 소속만(다중소속 단순화)
                members.setdefault(name, []).append(code)
        _theme_of = theme_of
        _theme_members = members
        _theme_mtime = mt
    except Exception as e:
        _log(f"[THEME] 멤버십 캐시 읽기 실패(직전 값 유지): {e}")


def _percentiles(items, key):
    """mid-rank percentile(0~1) — 동률은 평균 순위."""
    vals = sorted(key(it) for it in items)
    n = len(vals)
    out = {}
    for it in items:
        v = key(it)
        lo = bisect_left(vals, v)
        hi = bisect_right(vals, v)
        out[it["code"]] = (lo + (hi - lo) / 2.0) / n
    return out


def _zscore(v, mean, std):
    return (v - mean) / std if std > 0 else 0.0


def _at_or_before(buf, target_epoch, max_age=5.0):
    """target_epoch 이하 중 가장 가까운 샘플. 데이터 공백(예: 피더 정지 후 재기동)으로
    target보다 max_age(초) 넘게 오래된 샘플만 있으면 None — 옛 값을 30초전 값인 척 쓰지 않는다."""
    for sample in reversed(buf):
        if sample[0] <= target_epoch:
            return sample if (target_epoch - sample[0]) <= max_age else None
    return None


def _read_json_safely(path, last_good, state_flag, tag):
    try:
        mtime = path.stat().st_mtime
    except Exception as e:
        if not state_flag["stale"]:
            _hist_write(f"{tag}_STALE", "-", "-", f"파일 접근 실패: {e}")
            _log(f"[STALE] {tag} 접근 실패(직전 정상 데이터 유지): {e}")
            state_flag["stale"] = True
        return last_good, state_flag["mtime"]
    if mtime == state_flag["mtime"]:
        return last_good, mtime
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
        if state_flag["stale"]:
            _hist_write(f"{tag}_RECOVER", "-", "-", "")
            _log(f"[RECOVER] {tag} 정상 회복")
            state_flag["stale"] = False
        return parsed, mtime
    except Exception as e:
        if not state_flag["stale"]:
            _hist_write(f"{tag}_STALE", "-", "-", f"파싱 실패: {e}")
            _log(f"[STALE] {tag} 파싱 실패(직전 정상 데이터 유지): {e}")
            state_flag["stale"] = True
        return last_good, state_flag["mtime"]


def _reason_risk(role, pct, code):
    """규칙기반 템플릿(AI/LLM 미사용) — 임계값 넘는 항목만 문자열로."""
    reasons, risks = [], []
    if role == "valley":
        if pct.get("bottom_rebound_pct", 0) >= 0.8:
            reasons.append("저점 대비 반등 상위 20%")
        if pct.get("che_accel", 0) >= 0.8:
            reasons.append("반등 구간 체결강도 가속")
        if pct.get("volatility_pct", 0) >= 0.9:
            risks.append("변동폭 과도(상위 10%) — 되돌림 위험")
    elif role == "breakout":
        if pct.get("depth_compress", 0) >= 0.8:
            reasons.append("호가 총잔량 압축(돌파 직전 패턴)")
        if pct.get("money_accel", 0) >= 0.8:
            reasons.append("거래대금 가속 상위 20%")
        if pct.get("imbalance", 0) <= 0.2:
            risks.append("호가 매도우위 — 돌파 실패 위험")
    elif role == "ma_pullback":
        if pct.get("trend45", 0) >= 1.0:
            reasons.append("일봉 정배열 배지 보유")
        if pct.get("bottom_rebound_pct", 0) >= 0.7:
            reasons.append("이평 눌림 후 반등 시작")
        if pct.get("trend45", 0) < 1.0:
            risks.append("정배열 배지 없음 — 눌림 근거 약함")
    return reasons, risks


def main():
    _log("integrated_candidate_engine_v1 시작 — 읽기전용 · TR 0 · 주문 0 · SetRealReg 0")
    _log(f"입력 snap={SNAP} board={BOARD} trend={TREND} 출력={OUT} 폴링={POLL_SEC}s")

    buffers = {}  # code -> deque[(epoch, cur, ask_tot, bid_tot, rank, score)]
    snap_state = {"mtime": None, "stale": False}
    board_state = {"mtime": None, "stale": False}
    last_snap_raw = {}   # {"ts":..., "codes":{...}} 원본 그대로 — last_good 왕복용
    last_board = {}
    prev_top20 = set()
    prev_primary = {}

    while True:
        if datetime.now().strftime("%H%M") >= STOP_HM:
            _log(f"[SHUTDOWN] stop_hm={STOP_HM}")
            break
        loop_t0 = time.time()
        now = loop_t0

        _load_trend45()
        _load_theme_map()

        # ★[버그수정] last_good으로 넘기는 값은 반드시 _read_json_safely가 돌려주는 것과
        #   같은 모양(원본 {"ts","codes"} 딕셔너리)이어야 한다. 예전엔 이미 벗겨낸 codes만 넘겨서
        #   mtime 불변(파일 안 바뀐 틱)마다 .get("codes",{})가 빈 딕셔너리를 돌려줘 ask_tot/bid_tot가
        #   통째로 사라지던 버그(depth_compress_pct 전종목 -100% 고정으로 발견).
        snap_raw, snap_state["mtime"] = _read_json_safely(SNAP, last_snap_raw, snap_state, "SNAP")
        if isinstance(snap_raw, dict):
            last_snap_raw = snap_raw
        last_snap_codes = last_snap_raw.get("codes", {})
        board_raw, board_state["mtime"] = _read_json_safely(BOARD, last_board, board_state, "BOARD")
        if isinstance(board_raw, dict):
            last_board = board_raw

        board_status = last_board.get("status")
        board_items = {it["code"]: it for it in (last_board.get("all_items") or [])}

        # 버퍼 갱신 — board에 rank/score가 있는(=WARMUP/STALE 아닌) 종목만 대상
        for code, it in board_items.items():
            if it.get("rank") is None or it.get("score") is None:
                continue
            snap_rec = last_snap_codes.get(code) or {}
            cur = snap_rec.get("cur")
            ask_tot = snap_rec.get("ask_tot")
            bid_tot = snap_rec.get("bid_tot")
            buf = buffers.get(code)
            if buf is None:
                buf = deque()
                buffers[code] = buf
            if not (buf and buf[-1][0] == now):
                buf.append((now, cur, ask_tot, bid_tot, it["rank"], it["score"]))
            cutoff = now - BUFFER_MIN * 60
            while buf and buf[0][0] < cutoff:
                buf.popleft()

        for code in list(buffers.keys()):
            if code not in board_items or not buffers[code]:
                buffers.pop(code, None)

        valid = []
        for code, it in board_items.items():
            if it.get("rank") is None or it.get("score") is None:
                continue
            buf = buffers.get(code)
            if not buf:
                continue
            latest = buf[-1]
            row = dict(it)
            row["code"] = code
            row["_buf"] = buf
            valid.append(row)

        universe_count = len(board_items)
        valid_count = len(valid)

        if board_status != "OK" or valid_count < MIN_VALID:
            out_board = {
                "date": datetime.now().strftime("%Y%m%d"),
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "INSUFFICIENT_DATA",
                "universe_count": universe_count,
                "valid_count": valid_count,
                "attention_rank": [],
                "views": {"top5": [], "top10": [], "top20": [], "top40": []},
                "strategy_top10": {"valley": [], "breakout": [], "ma_pullback": []},
                "outlier_alerts": [],
            }
            try:
                _atomic_write_json(OUT, out_board)
            except Exception as e:
                _log(f"[WRITE] 출력 실패: {e}")
            elapsed = time.time() - loop_t0
            time.sleep(max(0.05, POLL_SEC - elapsed))
            continue

        # ── 횡단면(cross-sectional) 통계: che 분포(RS용), score 분포 ──
        che_vals = [r["che"] for r in valid if r.get("che") is not None]
        che_mean = sum(che_vals) / len(che_vals) if che_vals else 0.0
        che_std = (sum((x - che_mean) ** 2 for x in che_vals) / len(che_vals)) ** 0.5 if che_vals else 0.0

        for r in valid:
            buf = r["_buf"]
            latest = buf[-1]
            r["snapshot_age_sec"] = round(now - latest[0], 1)
            r["rs_che"] = round(_zscore(r.get("che") or 0.0, che_mean, che_std), 3)

            s30 = _at_or_before(buf, now - 30)
            r["rank_velocity"] = round(((s30[4] - r["rank"]) / 30.0), 3) if s30 else 0.0

            cur_vals = [s[1] for s in buf if s[0] >= now - VOL_WINDOW and s[1] is not None]
            if cur_vals:
                lo, hi = min(cur_vals), max(cur_vals)
                r["volatility_pct"] = round((hi - lo) / lo * 100.0, 3) if lo > 0 else 0.0
                r["bottom_rebound_pct"] = round((cur_vals[-1] / lo - 1.0) * 100.0, 3) if lo > 0 else 0.0
            else:
                r["volatility_pct"] = 0.0
                r["bottom_rebound_pct"] = 0.0

            depth30 = _at_or_before(buf, now - 30)
            if depth30 and depth30[2] is not None and depth30[3] is not None and (depth30[2] + depth30[3]) > 0:
                depth_now = (latest[2] or 0.0) + (latest[3] or 0.0)
                depth_before = depth30[2] + depth30[3]
                r["depth_compress_pct"] = round((depth_now - depth_before) / depth_before * 100.0, 3)
            else:
                r["depth_compress_pct"] = 0.0

            r["trend45"] = 1 if r["code"] in _trend_codes else 0

        # 이상치(자기 시계열 z-score) — che 자체 히스토리가 필요하므로 별도 코드별 deque 유지
        for r in valid:
            code = r["code"]
            hist = _che_history.setdefault(code, deque())
            hist.append((now, r.get("che") or 0.0))
            cutoff = now - VOL_WINDOW
            while hist and hist[0][0] < cutoff:
                hist.popleft()
            vals = [v for _, v in hist]
            if len(vals) >= 30:
                m = sum(vals) / len(vals)
                sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
                z = _zscore(r.get("che") or 0.0, m, sd)
            else:
                z = 0.0
            r["outlier_z"] = round(z, 2)
            r["outlier_flag"] = bool(abs(z) >= OUTLIER_Z and len(vals) >= 30)
        for code in list(_che_history.keys()):
            if code not in board_items:
                _che_history.pop(code, None)

        pct_score = _percentiles(valid, lambda r: r["score"])
        pct_vel = _percentiles(valid, lambda r: r["rank_velocity"])
        pct_rs = _percentiles(valid, lambda r: r["rs_che"])
        pct_rebound = _percentiles(valid, lambda r: r["bottom_rebound_pct"])
        pct_vol = _percentiles(valid, lambda r: r["volatility_pct"])
        pct_cheaccel = _percentiles(valid, lambda r: r["che_accel"] or 0.0)
        pct_compress = _percentiles(valid, lambda r: -r["depth_compress_pct"])
        pct_maccel = _percentiles(valid, lambda r: r["money_accel"] or 0.0)
        pct_imbalance = _percentiles(valid, lambda r: r["imbalance"] or 0.0)

        for r in valid:
            c = r["code"]
            att = (pct_score[c] * W_ATT_SCORE + pct_vel[c] * W_ATT_VEL + pct_rs[c] * W_ATT_RS)
            if r["outlier_flag"]:
                att += OUTLIER_BONUS
            r["attention_score"] = round(min(100.0, att), 2)

            r["valley_score"] = round(
                pct_rebound[c] * W_VAL_REBOUND + pct_vol[c] * W_VAL_VOL + pct_cheaccel[c] * W_VAL_CHEACCEL, 2)

            r["breakout_score"] = round(
                pct_compress[c] * W_BRK_COMPRESS + pct_rs[c] * W_BRK_RS + pct_maccel[c] * W_BRK_MACCEL, 2)

            trend_component = W_MAP_TREND if r["trend45"] else 0.0
            r["ma_pullback_score"] = round(trend_component + pct_rebound[c] * W_MAP_REBOUND, 2)

            scores3 = {"valley": r["valley_score"], "breakout": r["breakout_score"], "ma_pullback": r["ma_pullback_score"]}
            ordered = sorted(scores3.items(), key=lambda kv: -kv[1])
            r["primary_strategy"] = ordered[0][0]
            r["confidence"] = round(max(0.0, min(1.0, (ordered[0][1] - ordered[1][1]) / 100.0)), 3)

            pct_map = {
                "bottom_rebound_pct": pct_rebound[c], "che_accel": pct_cheaccel[c], "volatility_pct": pct_vol[c],
                "depth_compress": pct_compress[c], "money_accel": pct_maccel[c], "imbalance": pct_imbalance[c],
                "trend45": float(r["trend45"]),
            }
            reasons, risks = _reason_risk(r["primary_strategy"], pct_map, c)
            r["reasons"] = reasons
            r["risks"] = risks

            r.pop("_buf", None)

        # ── 테마 로테이션(집계·보너스) + 리더-팔로워(관측 전용, 점수 미반영) ──
        by_theme = {}
        for r in valid:
            th = _theme_of.get(r["code"])
            r["theme_name"] = th
            if th:
                by_theme.setdefault(th, []).append(r)

        for th, members in by_theme.items():
            if len(members) < 2:
                for r in members:
                    r["theme_flow_score"] = 0.0
                continue
            avg_att = sum(m["attention_score"] for m in members) / len(members)
            flow = round(THEME_BONUS_MAX * max(0.0, (avg_att - 50.0) / 50.0), 2)
            for r in members:
                r["theme_flow_score"] = flow
                r["attention_score"] = round(min(100.0, r["attention_score"] + flow), 2)

        # 종목별 "핫 진입시각" 갱신(테마 무관, 전 종목) — 리더팔로워 시차 계산용
        now_valid_codes = set()
        for r in valid:
            code = r["code"]
            now_valid_codes.add(code)
            if r["attention_score"] >= THEME_HOT_TH:
                _code_hot_since.setdefault(code, now)
            else:
                _code_hot_since.pop(code, None)
        for code in list(_code_hot_since.keys()):
            if code not in now_valid_codes:
                _code_hot_since.pop(code, None)

        for r in valid:
            r["is_theme_leader"] = False
            r["leader_lag_sec"] = None

        for th, members in by_theme.items():
            if len(members) < 2:
                continue
            leader = max(members, key=lambda m: m["attention_score"])
            leader["is_theme_leader"] = True
            leader_hot = _code_hot_since.get(leader["code"])
            prev_leader = _theme_leader_now.get(th)
            if prev_leader != leader["code"]:
                _hist_write("THEME_LEADER_CHANGE", leader["code"], leader["name"], f"theme={th}")
                _theme_leader_now[th] = leader["code"]
            if leader_hot is None:
                continue
            for m in members:
                if m is leader:
                    continue
                follower_hot = _code_hot_since.get(m["code"])
                if follower_hot is not None and follower_hot > leader_hot:
                    lag = round(follower_hot - leader_hot, 1)
                    m["leader_lag_sec"] = lag
                    if follower_hot == now:  # 이번 틱에 막 핫해진 순간(=최초 1회)만 기록 — 매초 반복 방지
                        _hist_write("LEADER_FOLLOW_OBSERVED", m["code"], m["name"],
                                    f"theme={th} leader={leader['code']} lag={lag}s(관측전용·점수미반영)")

        valid.sort(key=lambda r: -r["attention_score"])
        for i, r in enumerate(valid, 1):
            r["rank"] = i

        top20_codes = {r["code"] for r in valid[:20]}
        for r in valid[:20]:
            if r["code"] not in prev_top20:
                _hist_write("TOP20_IN", r["code"], r["name"], f"rank={r['rank']} attention={r['attention_score']}")
        for code in prev_top20 - top20_codes:
            _hist_write("TOP20_OUT", code, "", "")
        prev_top20 = top20_codes

        for r in valid:
            if r["outlier_flag"] and not prev_primary.get(r["code"] + "_outlier"):
                _hist_write("OUTLIER_ALERT", r["code"], r["name"], f"z={r['outlier_z']}")
            prev_primary[r["code"] + "_outlier"] = r["outlier_flag"]
            pp = prev_primary.get(r["code"])
            if pp is not None and pp != r["primary_strategy"]:
                _hist_write("PRIMARY_CHANGE", r["code"], r["name"], f"{pp}->{r['primary_strategy']}")
            prev_primary[r["code"]] = r["primary_strategy"]

        def _public(r):
            return {k: r.get(k) for k in _PUBLIC_FIELDS}

        attention_rank = [_public(r) for r in valid]
        strategy_top10 = {
            "valley": [_public(r) for r in sorted(valid, key=lambda r: -r["valley_score"])[:10]],
            "breakout": [_public(r) for r in sorted(valid, key=lambda r: -r["breakout_score"])[:10]],
            "ma_pullback": [_public(r) for r in sorted(valid, key=lambda r: -r["ma_pullback_score"])[:10]],
        }
        outlier_alerts = [_public(r) for r in valid if r["outlier_flag"]]

        out_board = {
            "date": datetime.now().strftime("%Y%m%d"),
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "OK",
            "universe_count": universe_count,
            "valid_count": valid_count,
            "attention_rank": attention_rank,
            "views": {
                "top5": attention_rank[:5], "top10": attention_rank[:10],
                "top20": attention_rank[:20], "top40": attention_rank[:40],
            },
            "strategy_top10": strategy_top10,
            "outlier_alerts": outlier_alerts,
        }
        try:
            _atomic_write_json(OUT, out_board)
        except Exception as e:
            _log(f"[WRITE] 출력 실패: {e}")

        elapsed = time.time() - loop_t0
        time.sleep(max(0.05, POLL_SEC - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
