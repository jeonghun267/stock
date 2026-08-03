# -*- coding: utf-8 -*-
"""
[월요일 아침 종합 점검기 v1  2026-06-13]  (친구님: 월요일 다 잘 도는지 확인)
오늘(6/13) 만든 변경들이 실제로 잘 켜지고 돌아가는지 자동 점검 → LOG/monday_health_check.txt 리포트.
READ-ONLY (아무것도 안 고침). 실행시각에 따라 가능한 항목만 점검(아침/오후).
스케줄: SAFEPLUS_MONDAY_HEALTHCHECK 09:05 + 15:10.
"""
import os, sys, io, csv, json, glob
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = Path(r"C:\stock_bot")
OUT = BASE / "LOG" / "monday_health_check.txt"
now = datetime.now()
today = now.strftime("%Y%m%d")
hhmm = now.hour * 100 + now.minute
R = []   # report lines
def line(s): R.append(s)
def ck(ok, name, detail=""):
    mark = "✅" if ok is True else ("⚠️" if ok is None else "❌")
    R.append(f"  {mark} {name}{('  — ' + detail) if detail else ''}")


def env(v):
    """User 영구 env를 레지스트리에서 직접 읽음(어느 프로세스서 돌려도 정확). 실패시 os.environ."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        try:
            val, _ = winreg.QueryValueEx(k, v)
            return str(val)
        finally:
            winreg.CloseKey(k)
    except Exception:
        return os.environ.get(v, "")


def fresh_min(p):
    p = Path(p)
    if not p.exists():
        return None
    return (now.timestamp() - p.stat().st_mtime) / 60.0


def main():
    line("=" * 64)
    line(f"[월요일 종합 점검] {now:%Y-%m-%d %H:%M}")
    line("=" * 64)

    # 1) 실탄/전략 스위치
    line("\n[1] 실탄·전략 스위치 (기대값과 일치?)")
    exp = {"SWING_LIVE": "YES", "EOD_PICK_LIVE": "NO",   # [6/14] QRISER 삭제로 점검 제외 · [7/18] EOD_PICK은 신규매수 중단(eod_gap이 실전)이 현행 — 기대값 NO로 교정
           "EOD_HONG_8TO1_ENABLE": "YES", "SB_REPEAT_ENABLE": "YES",
           "EOD_ANCHOR_ENABLE": "YES", "SWING_ANCHOR_ENABLE": "YES",
           "SWING_BOTTOM_LOOKBACK": "5", "EOD_BOTTOM_CEIL_MAX": "50",
           "RTRISK_REPEAT_ENABLE": "NO", "EXEC_SAFEPLUS_ENABLE": "NO",
           # [6/14 신규] 오늘 켠 스위치도 점검
           "MAKE_RT_LEADER_ONLY": "NO",  # [7/18] 현행 env가 NO로 운용 중 — 낡은 기대값 교정
           "SWING_HIGHER_LOW": "YES", "US_CRASH_BLOCK_ENABLE": "YES"}
    for k, want in exp.items():
        got = env(k) or ("(미설정=코드기본)" if k in ("EOD_BOTTOM_CEIL_MAX",) else "")
        ok = (env(k).upper() == want.upper()) if env(k) else (k == "EOD_BOTTOM_CEIL_MAX")
        ck(ok if env(k) or k == "EOD_BOTTOM_CEIL_MAX" else None, k, f"기대 {want} / 실제 {got or '(빈값)'}")

    # 2) 차단 깃발 (없어야 정상)
    line("\n[2] 매수 차단 깃발 (없어야 정상)")
    kill = list(glob.glob(str(BASE / "data" / "kill_switch.flag")))
    kill = [k for k in kill if not k.endswith("removed")]
    ck(len(kill) == 0, "kill_switch.flag", "없음" if not kill else f"있음! {kill}")
    tg = BASE / "data" / "trading_gate.flag"
    tg_block = False
    if tg.exists():
        try:
            j = json.loads(tg.read_text(encoding="utf-8"))
            tg_block = (str(j.get("mode", "")).upper() == "BLOCK" and str(j.get("expires_at", "")) > now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
    ck(not tg_block, "trading_gate BLOCK", "정상(차단 없음)" if not tg_block else "BLOCK 활성!")

    # 3) 보유 ISC(095340) — 09:00 시가매도 됐나
    line("\n[3] 보유 ISC(095340) 09:00 시가매도")
    rt = BASE / "data" / "rt_open_positions.json"
    isc_held = False
    if rt.exists():
        try:
            pos = json.loads(rt.read_text(encoding="utf-8"))
            isc_held = "095340" in pos and float(pos.get("095340", {}).get("qty", 0) or 0) > 0
        except Exception:
            pass
    if hhmm < 905:
        ck(None, "ISC 매도", "아직 09:00 전 — 점검 보류")
    else:
        ck(not isc_held, "ISC 매도완료", "rt_open에서 사라짐(매도됨)" if not isc_held else "아직 보유중! 09:00 매도 확인 필요")

    # 4) 코스피 앵커 데이터 (09:30 이후)
    line("\n[4] 코스피 앵커 데이터 (09:30 수집)")
    anc = BASE / "data" / "theme" / "kospi_anchor.csv"
    if hhmm < 935:
        ck(None, "앵커 수집", "아직 09:30 전 — 점검 보류")
    else:
        fm = fresh_min(anc)
        if fm is None:
            ck(False, "kospi_anchor.csv", "없음! 수집기 확인 필요")
        else:
            try:
                rows = list(csv.DictReader(io.open(anc, encoding="utf-8-sig")))
                up = sum(1 for r in rows if float(r.get("chg_pct", 0) or 0) > 0)
                ck(len(rows) >= 10 and fm < 360, "kospi_anchor.csv",
                   f"{len(rows)}개(상승 {up}) · {fm:.0f}분전")
            except Exception as e:
                ck(False, "kospi_anchor.csv 파싱", str(e))

    # 5) 오늘 로그에 새 기능 발화 흔적 (14:55 종가매수 후)
    line("\n[5] 오늘 새 기능 로그 흔적")
    logdirs = [BASE / "data" / "LOG", BASE / "LOG"]
    def grep_today(tag):
        hit = 0
        for d in logdirs:
            for f in d.glob("*.log"):
                try:
                    if (now.timestamp() - f.stat().st_mtime) / 3600 > 24:
                        continue
                    txt = f.read_text(encoding="utf-8", errors="replace")
                    hit += txt.count(tag)
                except Exception:
                    continue
        return hit
    if hhmm < 1500:
        ck(None, "종가매수 로그(14:55)", "아직 장중 — 오후 점검에서 확인")
    else:
        for tag in ("[SB-REPEAT]", "[HONG-8TO1]", "[BOTTOM-CEIL]", "[ANCHOR]"):
            n = grep_today(tag)
            ck(n > 0 or None, f"{tag} 발화", f"{n}회" if n else "흔적 없음(확인 요)")

    # 6) 오류/치명 로그
    line("\n[6] 오늘 치명 오류 ([FATAL]/Traceback)")
    fatal = 0
    for d in logdirs:
        for f in d.glob("*.log"):
            try:
                # [7/18] 자기 로그 제외 — 리포트 제목의 "[FATAL]" 문자열이 실행마다 쌓여 매번 +1 오탐(88→89건…)
                if f.name == "sched_SAFEPLUS_MONDAY_HEALTHCHECK.log":
                    continue
                if (now.timestamp() - f.stat().st_mtime) / 3600 > 24:
                    continue
                txt = f.read_text(encoding="utf-8", errors="replace")
                fatal += txt.count("[FATAL]") + txt.count("Traceback (most recent call last)")
            except Exception:
                continue
    ck(fatal == 0 or None, "치명오류", "없음" if fatal == 0 else f"{fatal}건 — 확인 권장")

    # 7) score_eod 신선도
    line("\n[7] 스코어보드(score_eod) 신선도")
    se = BASE / "data" / "scoreboard" / "score_eod.csv"
    fm = fresh_min(se)
    if fm is None:
        ck(False, "score_eod.csv", "없음")
    else:
        ck(fm < 1440, "score_eod.csv", f"{fm:.0f}분전 갱신")

    # ════════════════════════════════════════════════════════════
    # [2026-06-25 추가] 오늘 교훈 기반 점검 — 락크래시·커버리지·false-death·멀티픽·게이트이력
    # ════════════════════════════════════════════════════════════
    import re
    today_dash = now.strftime("%Y-%m-%d")
    def count_in(path, pat):
        p = Path(path)
        if not p.exists():
            return None
        try:
            n = 0
            for ln in io.open(p, encoding="utf-8", errors="replace"):
                if today_dash in ln and pat in ln:
                    n += 1
            return n
        except Exception:
            return None

    # [8] 수집기 락 경합 크래시 (잦으면 워치독 false-death/중복수집 위험)
    line("\n[8] 수집기 락 경합 크래시 (락 획득 실패)")
    lc = count_in(BASE / "LOG" / "collector_1m.log", "락 획득 실패")
    if lc is None:
        ck(None, "collector_1m.log", "로그 없음")
    else:
        ck(lc == 0, "락 획득 실패 크래시",
           "0건(정상)" if lc == 0 else f"{lc}건 — 워치독 false-death/중복수집 의심(HB임계 확인)")

    # [9] 수집 커버리지 갭 (신고가인데 1분봉 미수집 = 돌파 확정 불가)
    line("\n[9] 수집 커버리지 갭 (신고가 미수집 종목수)")
    miss = set()
    nhp = BASE / "data" / "LOG" / "newhigh_breakout_scanner.log"
    if nhp.exists():
        try:
            for ln in io.open(nhp, encoding="utf-8", errors="replace"):
                if today_dash in ln and "미수집(prices_1m" in ln:
                    m = re.search(r"신고가 (\d{6})", ln)
                    if m:
                        miss.add(m.group(1))
            ck(len(miss) <= 10, "미수집 신고가 종목",
               f"{len(miss)}종목(대부분 일시지연)" if len(miss) <= 10
               else f"{len(miss)}종목 — 커버리지 구멍(수집기 universe/inject 확인)")
        except Exception as e:
            ck(None, "newhigh scanner 파싱", str(e))
    else:
        ck(None, "newhigh scanner log", "없음")

    # [10] 워치독 false-death 재시작 (살아있는 수집기를 죽음으로 오판)
    line("\n[10] 워치독 false-death 재시작 (PROCESS_DEAD)")
    fd = count_in(BASE / "LOG" / f"watchdog_collect_1m_{today}.log", "reason=PROCESS_DEAD")
    if fd is None:
        ck(None, "watchdog log", "없음")
    else:
        ck(fd <= 1, "PROCESS_DEAD 재시작",
           f"{fd}건(정상범위)" if fd <= 1 else f"{fd}건 — HB임계 낮아 false-death 의심")

    # [11] NEW_PB 멀티픽 보유종목수 (≤ MAX_POS)
    line("\n[11] NEW_PB 보유종목수 (멀티픽 한도)")
    maxpos = int(env("NEW_PB_MAX_POS") or "5")
    npp = BASE / "data" / "new_pb_positions.json"
    if npp.exists():
        try:
            d = json.loads(npp.read_text(encoding="utf-8"))
            opens = [k for k, v in d.items() if isinstance(v, dict) and v.get("status") == "OPEN"]
            ck(len(opens) <= maxpos, "NEW_PB 보유",
               f"{len(opens)}/{maxpos}종목" + (f": {opens}" if opens else " (없음)"))
        except Exception as e:
            ck(False, "new_pb_positions 파싱", str(e))
    else:
        ck(None, "new_pb_positions.json", "없음(매수 0)")

    # [12] 트레이딩 게이트 BLOCK 이력 (CSV_IDLE 등 매수금지 발생 = 기회손실)
    line("\n[12] 트레이딩 게이트 BLOCK 이력")
    gh = BASE / "LOG" / "gate_history.csv"
    if gh.exists():
        try:
            blk = 0
            reasons = set()
            for r in csv.DictReader(io.open(gh, encoding="utf-8-sig")):
                if str(r.get("ts", "")).startswith(today_dash) and str(r.get("mode", "")).upper() == "BLOCK":
                    blk += 1
                    reasons.add(str(r.get("reason", ""))[:22])
            ck(blk == 0, "BLOCK 발생",
               "없음" if blk == 0 else f"{blk}회 — {sorted(reasons)[:3]} (그 시간 매수금지)")
        except Exception as e:
            ck(None, "gate_history 파싱", str(e))
    else:
        ck(None, "gate_history.csv", "없음")

    line("\n" + "=" * 64)
    line("※ ⚠️=시각상 아직 점검불가(나중 재실행) / ❌=확인 필요 / ✅=정상")
    txt = "\n".join(R)
    print(txt)
    try:
        OUT.write_text(txt + "\n", encoding="utf-8")
        print(f"\n→ 리포트 저장: {OUT}")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FATAL] 점검기 오류: {e}")
        import traceback; traceback.print_exc()
