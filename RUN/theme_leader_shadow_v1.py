# -*- coding: utf-8 -*-
"""
[2026-07-11 밤 친구님 "등락1등+대금1등, 등락1등+대금2등 두 개를 그림자로 남겨줘"] 테마 주도주 그림자 v1
근거(7/11 밤 3분봉 백테·달린테마 62건): 등락1등+대금2등 = 10시 진입도 +30분 +3.19%/82% (전 조합 최강)
  · 등락1등+대금1등(쌍끌이) = 09:30 +1시간 +2.94%/75% · 부하보다 우위. 후행편향 있어 그림자 실측으로 확정.

동작(주문 0 · 기록 전용):
  record(기본): 장중 3분 태스크 — opt10032 코스닥 대금상위 + opt10027 등락률상위(영웅문 0181 화면
    상당·친구님 7/11 "0181 쓰고 있니?" → 합류: 급등인데 돈이 아직 안 붙은 놈이 바로 표적이라 필수)
    두 스냅샷 합집합(TR 2) × 네이버 테마 → "달리는 테마"(스냅샷 내 멤버 3+ · 평균등락 +3%↑)에서
    등락률 1등 종목의 대금 순위가 1등이면 신호 [쌍끌이], 2등이면 [대금2등] — 테마당 하루 1회.
    opt10027 합류 끄기: THLDR_UPDOWN=NO (대금은 금액 필드 없으면 현재가x거래량 근사).
  fill: 15:40 — 당일 기록의 빈 성적을 3분봉(opt10080)으로 채움(+30분/+1시간/+2시간/1시간내최고/종가).
  report: 신호별 성적 요약 출력(수요일 보고용).

출력: data/shadow/theme_leader_shadow.csv(이력) + ★data/테마주도주.json(공용 신호·매 실행 갱신 —
  친구님 7/12 "선별기에 넣어서 전략들이 공동으로 사용" → 선별판 👑배지·전략들은 theme_leader.py 헬퍼로 소비)
상태: theme_leader_state.json · 로그: LOG/theme_leader_shadow.log
끄기: 태스크 SAFEPLUS_THEME_LEADER_SHADOW(+_FILL) Disable · env THLDR_ON=NO
주의: 장중 달림 판정은 '스냅샷 내 멤버 3+·평균 +3%'로 백테(전멤버 8+·일봉 확정)와 정의가 약간 다름(실시간 근사).
"""
import sys, os, csv, json, time, collections
from datetime import datetime
from pathlib import Path
sys.path.insert(0, r"C:\stock_bot\RUN")

MEMB = Path(r"C:\stock_bot\data\theme\theme_membership_naver.csv")
OUT = Path(r"C:\stock_bot\data\shadow\theme_leader_shadow.csv")
STATE = Path(r"C:\stock_bot\data\shadow\theme_leader_state.json")
LOG = Path(r"C:\stock_bot\data\LOG\theme_leader_shadow.log")
HOT_CHG = float(os.environ.get("THLDR_HOT_CHG", "3.0"))
MIN_MEM = int(os.environ.get("THLDR_MIN_MEM", "3"))
HEADER = ["일자", "시각", "신호", "테마", "종목코드", "종목명", "진입가", "등락률", "대금억",
          "스냅샷멤버수", "수익30분", "수익1시간", "수익2시간", "최고1시간내", "수익종가"]

# ══ [2026-07-21 오사장님 지시 — 진짜 테마대장 판별 강화] 기존 쌍끌이/대금2등 판정(record() 본문)은
#   전혀 안 건드림. 새 TR·새 실시간등록 없음 — micro_rank_board.json(Money Flow)·돈흐름_che_state.json
#   (체결강도) 둘 다 이미 다른 엔진이 계산해둔 파일을 읽기전용으로만 재사용한다.
TRUE_LEADER_GAP_PCT = float(os.environ.get("TRUE_LEADER_GAP_PCT", "30"))   # 대금 1등이 2등보다 이 %이상 커야
TRUE_LEADER_CHE_MIN = float(os.environ.get("TRUE_LEADER_CHE_MIN", "110"))  # 체결강도 이 값 이상이어야 "강함"
MFE_BOARD_FOR_TL = Path(r"C:\stock_bot\data\micro_rank_board.json")
CHE_STATE_FOR_TL = Path(r"C:\stock_bot\data\돈흐름_che_state.json")
TRUE_LEADER_LOG = Path(r"C:\stock_bot\data\shadow\true_leader_check.csv")
TL_HEADER = ["일자", "시각", "테마", "종목코드", "종목명", "1등거래대금억", "2등거래대금억",
             "차이%", "MoneyFlow순위", "MONEY_START", "체결강도", "동반종목수", "TRUE_LEADER"]


def _mf_board_map():
    """오늘자 micro_rank_board.json → {code: item}. 실패/오늘자 아니면 빈 dict(검증로그만 못 채움·매수 무관)."""
    try:
        d = json.loads(MFE_BOARD_FOR_TL.read_text(encoding="utf-8-sig"))
        if str(d.get("date") or "") != datetime.now().strftime("%Y%m%d"):
            return {}
        return {str(it.get("code")).zfill(6): it for it in (d.get("all_items") or []) if it.get("code")}
    except Exception:
        return {}


def _che_state_map():
    try:
        return json.loads(CHE_STATE_FOR_TL.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _true_leader_log_row(row):
    try:
        TRUE_LEADER_LOG.parent.mkdir(parents=True, exist_ok=True)
        new = not TRUE_LEADER_LOG.exists()
        with TRUE_LEADER_LOG.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=TL_HEADER)
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        log("TRUE_LEADER 로그 실패(무시): %s" % e)

def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line)
    except Exception:
        pass
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def num(v):
    s = str(v).strip().replace(",", "").replace("--", "-").lstrip("+")
    try:
        return float(s)
    except ValueError:
        return 0.0

def load_rows():
    if not OUT.exists():
        return []
    with OUT.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def save_rows(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, OUT)

def theme_map():
    themes = collections.defaultdict(list)
    with MEMB.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            themes[r["theme_name"]].append(str(r["code"]).zfill(6))
    return themes

def record():
    if os.environ.get("THLDR_ON", "YES").strip().upper() != "YES":
        return
    now = datetime.now()
    hm = now.strftime("%H%M")
    if now.weekday() >= 5 or not ("0906" <= hm <= "1430"):
        return
    from broker_client import BrokerClient, is_broker_alive
    if not is_broker_alive():
        return
    bc = BrokerClient()
    try:
        r = bc.tr("opt10032", {"시장구분": "101", "관리종목포함": "0"},
                  ["종목코드", "종목명", "현재가", "등락률", "등락율", "전일대비", "거래대금"],
                  screen_no="9747", timeout_sec=10.0)
        recs = (r.get("data") or {}).get("records") or []
    except Exception as e:
        log("opt10032 실패: %s" % e); return
    snap = {}
    for x in recs:
        code = str(x.get("종목코드", "")).strip().replace("_AL", "").zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue
        price = abs(num(x.get("현재가")))
        chg = num(x.get("등락률")) or num(x.get("등락율"))
        if chg == 0 and price > 0:
            diff = num(x.get("전일대비"))
            prev = price - diff
            chg = diff / prev * 100 if prev > 0 else 0.0
        snap[code] = {"name": str(x.get("종목명", "")).strip(), "price": price,
                      "chg": chg, "val": num(x.get("거래대금"))}
    if not snap:
        return
    # [7/11 밤 친구님 "0181(등락률상위) 쓰고 있니?"] opt10027 합류 — 대금상위 200 밖의 급등주도
    #   등락1등 판정에 포함(돈이 아직 안 붙은 급등 = 대금2등 신호의 표적). 실패 시 opt10032만(fail-open).
    if os.environ.get("THLDR_UPDOWN", "YES").strip().upper() == "YES":
        try:
            r2 = bc.tr("opt10027", {"시장구분": "101", "정렬구분": "1", "거래량조건": "0000",
                                    "종목조건": "0", "신용조건": "0", "상하한포함": "1"},
                       ["종목코드", "종목명", "현재가", "등락률", "거래량", "금액"],
                       screen_no="9747", timeout_sec=8.0)
            for x in ((r2.get("data") or {}).get("records") or []):
                code = str(x.get("종목코드", "")).strip().lstrip("A").replace("_AL", "").zfill(6)
                if len(code) != 6 or not code.isdigit() or code in snap:
                    continue
                price = abs(num(x.get("현재가")))
                chg = num(x.get("등락률"))
                if price <= 0 or not (0 < chg <= 31.0):   # 극단(신규상장 노이즈) 제외
                    continue
                val = num(x.get("금액"))
                if val <= 0:
                    val = price * num(x.get("거래량")) / 1e6   # 백만원 근사(opt10032 단위 맞춤)
                snap[code] = {"name": str(x.get("종목명", "")).strip(), "price": price,
                              "chg": chg, "val": val}
        except Exception as e:
            log("opt10027 합류 실패(무시): %s" % e)
    today = now.strftime("%Y%m%d")
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {"seen": []}
    seen = set(st.get("seen") or [])
    rows = load_rows()
    n_new = 0
    mf_map = _mf_board_map()          # ★TRUE_LEADER용 — 루프 밖에서 1회만 읽음(테마마다 재읽기 낭비 방지)
    che_map = _che_state_map()
    true_leaders = []
    for th, members in theme_map().items():
        grp = [(m, snap[m]) for m in set(members) if m in snap and snap[m]["price"] > 0]
        if len(grp) < MIN_MEM:
            continue
        if sum(g["chg"] for _m, g in grp) / len(grp) < HOT_CHG:
            continue
        top_chg = max(grp, key=lambda z: z[1]["chg"])
        by_val = sorted(grp, key=lambda z: -z[1]["val"])
        # ══ [TRUE_LEADER 판별] 등락률과 무관하게 "이 테마의 거래대금 1등"을 그대로 검사 —
        #   기존 top_chg/vrank/sig 판정(바로 아래)과 완전 독립·무접촉. ①거래대금1위=by_val[0]
        #   자체 ②2등과 격차 ③Money Flow(MONEY_START) ④체결강도. 전부 이미 계산된 값 재사용.
        if len(by_val) >= 2 and by_val[1][1]["val"] > 0:
            t1_code, t1 = by_val[0]
            t2_code, t2 = by_val[1]
            gap_pct = (t1["val"] / t2["val"] - 1) * 100
            mf_it = mf_map.get(t1_code) or {}
            mf_start = bool(mf_it.get("money_start"))
            mf_rank = mf_it.get("money_flow_rank")
            che_v = (che_map.get(t1_code) or {}).get("last")
            che_strong = bool(che_v is not None and che_v >= TRUE_LEADER_CHE_MIN)
            true_leader = bool(gap_pct >= TRUE_LEADER_GAP_PCT and mf_start and che_strong)
            _true_leader_log_row({
                "일자": today, "시각": now.strftime("%H:%M:%S"), "테마": th,
                "종목코드": t1_code, "종목명": t1["name"],
                "1등거래대금억": round(t1["val"] / 100, 1), "2등거래대금억": round(t2["val"] / 100, 1),
                "차이%": round(gap_pct, 1), "MoneyFlow순위": mf_rank if mf_rank is not None else "",
                "MONEY_START": mf_start, "체결강도": che_v if che_v is not None else "",
                "동반종목수": len(grp), "TRUE_LEADER": true_leader,
            })
            if true_leader:
                # ★[2026-07-21 오사장님 지시] "부하를 끌고 있는 대장" — 이미 계산된 grp(테마
                # 스냅샷 동반상승 종목수)를 그대로 재사용. 새 계산 없음. 우선순위 가중치로만 씀.
                true_leaders.append({"code": t1_code, "name": t1["name"], "theme": th,
                                      "gap_pct": round(gap_pct, 1), "che": che_v, "members": len(grp)})
        vrank = next(i + 1 for i, (m, _g) in enumerate(by_val) if m == top_chg[0])
        if vrank == 1:
            sig = "쌍끌이"
        elif vrank == 2:
            sig = "대금2등"
        else:
            continue
        key = "%s:%s" % (today, th)
        key2 = "%s:%s:%s" % (today, top_chg[0], sig)
        if key in seen or key2 in seen:
            continue
        seen.add(key); seen.add(key2)
        g = top_chg[1]
        rows.append({"일자": today, "시각": now.strftime("%H:%M"), "신호": sig, "테마": th,
                     "종목코드": top_chg[0], "종목명": g["name"], "진입가": g["price"],
                     "등락률": round(g["chg"], 1), "대금억": round(g["val"] / 100, 0),
                     "스냅샷멤버수": len(grp),
                     "수익30분": "", "수익1시간": "", "수익2시간": "", "최고1시간내": "", "수익종가": ""})
        n_new += 1
        log("신호 %s %s %s(%s) 진입가 %s 등락 %.1f%% 대금 %.0f억" %
            (sig, th, g["name"], top_chg[0], format(g["price"], ",.0f"), g["chg"], g["val"] / 100))
    if n_new:
        save_rows(rows)
    st["seen"] = sorted(seen)[-2000:]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    # [7/12 친구님 "전략들이 공동으로 사용"] 공용 신호 파일 — 당일 신호 전체 + 갱신시각(매 실행 갱신)
    try:
        pub = Path(r"C:\stock_bot\data\테마주도주.json")
        sigs = [{"code": r["종목코드"], "name": r["종목명"], "signal": r["신호"], "theme": r["테마"],
                 "time": r["시각"], "entry": r["진입가"], "chg": r["등락률"], "val_eok": r["대금억"]}
                for r in rows if r["일자"] == today]
        tmp = pub.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": now.strftime("%Y-%m-%d %H:%M:%S"), "date": today,
                                   "signals": sigs, "true_leaders": true_leaders},
                                   ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, pub)
    except Exception as e:
        log("공용 신호 파일 쓰기 실패(무시): %s" % e)

def fill():
    from broker_client import BrokerClient, is_broker_alive
    today = datetime.now().strftime("%Y%m%d")
    rows = load_rows()
    todo = [r for r in rows if r["일자"] == today and not str(r.get("수익종가", "")).strip()]
    if not todo:
        log("fill: 채울 기록 없음"); return
    if not is_broker_alive():
        log("fill: 브로커 죽음 — 다음 기회에"); return
    bc = BrokerClient()
    bars_by_code = {}
    for code in sorted({r["종목코드"] for r in todo}):
        time.sleep(0.35)
        try:
            r = bc.tr("opt10080", {"종목코드": code, "틱범위": "3", "수정주가구분": "1"},
                      ["체결시간", "현재가"], screen_no="9748", timeout_sec=8.0)
            recs = (r.get("data") or {}).get("records") or []
        except Exception:
            recs = []
        lst = []
        for x in recs[::-1]:
            ts = str(x.get("체결시간", "")).strip()
            if len(ts) >= 12 and ts[:8] == today:
                lst.append((ts[8:12], abs(num(x.get("현재가")))))
        bars_by_code[code] = sorted(set(lst))
    n_fill = 0
    for r in todo:
        lst = bars_by_code.get(r["종목코드"]) or []
        if len(lst) < 10:
            continue
        entry_hm = r["시각"].replace(":", "")
        ei = None
        for i, (t, _c) in enumerate(lst):
            if t >= entry_hm:
                ei = i; break
        if ei is None:
            continue
        e = num(r["진입가"])
        if e <= 0:
            continue
        def px(nb):
            return lst[min(ei + nb, len(lst) - 1)][1]
        r["수익30분"] = round((px(10) - e) / e * 100, 2)
        r["수익1시간"] = round((px(20) - e) / e * 100, 2)
        r["수익2시간"] = round((px(40) - e) / e * 100, 2)
        seg = lst[ei + 1:ei + 21]
        hi = max((c for _t, c in seg), default=e)
        r["최고1시간내"] = round((hi - e) / e * 100, 2)
        r["수익종가"] = round((lst[-1][1] - e) / e * 100, 2)
        n_fill += 1
    save_rows(rows)
    log("fill: %d건 성적 기입" % n_fill)

def report():
    rows = [r for r in load_rows() if str(r.get("수익종가", "")).strip()]
    if not rows:
        print("기록 없음"); return
    for sig in ("쌍끌이", "대금2등"):
        grp = [r for r in rows if r["신호"] == sig]
        print("\n■ %s (n=%d)" % (sig, len(grp)))
        if not grp:
            continue
        for col in ("수익30분", "수익1시간", "수익2시간", "최고1시간내", "수익종가"):
            v = [num(r[col]) for r in grp]
            avg = sum(v) / len(v)
            win = sum(1 for a in v if a > 0) / len(v) * 100
            print("  %s: 평균 %+.2f%% · 플러스 %.0f%%" % (col, avg, win))

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "record"
    if mode == "fill":
        fill()
    elif mode == "report":
        report()
    else:
        record()
