# -*- coding: utf-8 -*-
"""
[코스피 앵커 대형주 수집기 v1  2026-06-13]  (친구님: 코스피 앵커 참조)
주요 코스피 대형주(테마 앵커)의 당일 등락률을 조회 → DATA/theme/kospi_anchor.csv.
종가매수 8→1 / 스윙이 "코스닥 후보가 같은 테마 앵커보다 강한가"를 보는 데 사용(보조 보너스).
백테 검증(1년): 후보>앵커 익일갭 +0.28%p / 4일 +0.55%p (앵커상승&후보강함 익일+0.98%·4일+0.87%).
broker_client(키움 OCX 공유) opt10001. READ-ONLY 시세. 매매 무연결. 무크래시.
스케줄(권장): SAFEPLUS_KOSPI_ANCHORS 09:30·14:50 (종가매수/스윙 픽 직전).
사용: python -X utf8 collect_kospi_anchors_v1.py [--cache-min=N]
"""
import sys, csv, time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, r"C:\stock_bot\RUN")
OUT = Path(r"C:\stock_bot\DATA\theme\kospi_anchor.csv")

# 주요 코스피 앵커(테마 대형주). 테마-앵커 연결은 소비측이 theme_membership_naver로 자동(앵커가 그 테마 멤버면 매칭).
ANCHORS = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차", "000270": "기아",
    "005490": "POSCO홀딩스", "034020": "두산에너빌리티", "329180": "HD현대중공업",
    "042660": "한화오션", "012450": "한화에어로스페이스", "064350": "현대로템",
    "207940": "삼성바이오로직스", "068270": "셀트리온", "373220": "LG에너지솔루션",
    "006400": "삼성SDI", "051910": "LG화학", "035420": "NAVER", "035720": "카카오",
    "105560": "KB금융", "055550": "신한지주", "015760": "한국전력", "010130": "고려아연",
    "011200": "HMM", "028260": "삼성물산", "066570": "LG전자", "096770": "SK이노베이션",
    "003670": "포스코퓨처엠", "009540": "HD한국조선해양",
}


def _f(v):
    s = str(v).strip().replace(",", "")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def main():
    cache_min = 0.0
    for a in sys.argv[1:]:
        if a.startswith("--cache-min="):
            try: cache_min = float(a.split("=", 1)[1])
            except ValueError: pass
    if cache_min > 0 and OUT.exists():
        try:
            if (time.time() - OUT.stat().st_mtime) / 60.0 < cache_min:
                print("[ANCHOR] cache fresh skip"); return
        except OSError:
            pass
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            print("[ANCHOR] broker dead → skip(기존 파일 유지)"); return
        bc = BrokerClient()
        rows = []
        for i, (code, name) in enumerate(ANCHORS.items()):
            try:
                r = bc.tr("opt10001", {"종목코드": code},
                          ["종목명", "현재가", "전일대비", "등락율", "대비기호"],
                          screen_no="9704", timeout_sec=5.0)
                recs = (r.get("data") or {}).get("records") or []
                if not recs:
                    continue
                rec = recs[0]
                chg = _f(rec.get("등락율", "0"))
                if chg == 0.0:   # 등락율 빈값 → 현재가/전일대비로 산출
                    price = abs(_f(rec.get("현재가", "0")))
                    diff = abs(_f(rec.get("전일대비", "0")))
                    sign = str(rec.get("대비기호", "")).strip()
                    if sign in ("4", "5"):
                        diff = -diff
                    prev = price - diff
                    chg = round(diff / prev * 100, 2) if prev > 0 else 0.0
                rows.append({"code": code, "name": name, "chg_pct": round(chg, 2),
                             "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                time.sleep(0.25)   # TR 레이트 보호
            except Exception as _ce:
                print(f"[ANCHOR] {code} 조회 실패: {_ce}")
                continue
        if not rows:
            print("[ANCHOR] 수집 0 → 기존 파일 유지"); return
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["code", "name", "chg_pct", "ts"])
            w.writeheader(); w.writerows(rows)
        up = sum(1 for r in rows if r["chg_pct"] > 0)
        print(f"[ANCHOR] {len(rows)}개 수집 (상승 {up}) → {OUT.name}")
    except Exception as e:
        print(f"[ANCHOR] fail: {e}")


if __name__ == "__main__":
    main()
