# -*- coding: utf-8 -*-
"""
하락일 판정기 v1 (읽기 전용 - 주문/TR 없음)

친구님 승인 2026-08-08: 09:30 깨진반등률로 그날을 판정해 S02 매수 게이트에 공급.
- 재료: data\shadow\mf_1s_capture\mf_1s_당일.csv 의 09:00~09:30 부분 (가격만, 분봉 압축)
- 계산: 고점-4% 하락 마디 안의 +1% 반등(09:25까지) 중 09:30까지 신저가로 깨진 비율
- 판정: 깨진반등률 >= 47% -> 하락일 의심 (문턱은 12일 재생 기준 - 전방 검증 중)
- 출력: data\day_gate\day_judge_YYYYMMDD.json  (S02 게이트가 읽음)

근거: 12일 재생 - 게이트 적용 시 건당기대 -0.315% -> +0.016% (메모리 stockbot-20260808-*)
롤백: 태스크 SAFEPLUS_DAY_JUDGE 비활성화 (판정 파일이 없으면 게이트는 아무것도 안 함)
"""
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

BASE = r'C:\stock_bot'
SRC_DIR = os.path.join(BASE, 'data', 'shadow', 'mf_1s_capture')
OUT_DIR = os.path.join(BASE, 'data', 'day_gate')

EPI_DEPTH = 0.04            # 하락 마디 문턱 -4%
BOUNCE = 1.01               # 반등 문턱 +1%
CUT_ROW = '09:30:59'        # 읽기 마감
CUT_BOUNCE = '09:25'        # 반등 인정 마감(깨질 시간 5분 확보)
THRESHOLD = float(os.environ.get('DAY_JUDGE_TH', '47.0'))


def morning_minutes(path):
    """09:30:59까지만 읽어 code -> [(HH:MM, close)] 분봉 압축 (가격 원값만 사용)"""
    last = {}
    with open(path, encoding='utf-8', errors='replace') as fh:
        fh.readline()
        for line in fh:
            parts = line.split(',', 3)
            if len(parts) < 3:
                continue
            ts, code, price = parts[0], parts[1], parts[2]
            if ts[11:19] > CUT_ROW:
                break
            if len(code) != 6 or not price:
                continue
            try:
                p = float(price)
            except ValueError:
                continue
            if p <= 0:
                continue
            last[(code, ts[11:16])] = p
    by_code = defaultdict(list)
    for (code, minute), p in last.items():
        by_code[code].append((minute, p))
    return {c: sorted(v) for c, v in by_code.items()}


def broken_rate(series_map):
    """장세일지/12일 소급과 동일 정의"""
    n = broken = 0
    for rows in series_map.values():
        if len(rows) < 5:
            continue
        peak = rows[0][1]
        in_ep = False
        low = None
        pend = None
        for minute, p in rows:
            if not in_ep:
                if p > peak:
                    peak = p
                elif (peak - p) / peak >= EPI_DEPTH:
                    in_ep = True
                    low = p
            else:
                if p < low:
                    if pend is not None:
                        n += 1
                        broken += 1        # 반등 뒤 신저가 = 깨짐
                        pend = None
                    low = p
                elif pend is None and p >= low * BOUNCE and minute <= CUT_BOUNCE:
                    pend = minute
                if p >= peak:
                    if pend is not None:
                        n += 1             # 고점 회복 = 안 깨짐
                        pend = None
                    in_ep = False
                    peak = p
        if pend is not None:
            n += 1                          # 09:30까지 안 깨짐 = 안 깨짐
    return n, broken


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y%m%d')
    src = os.path.join(SRC_DIR, 'mf_1s_%s.csv' % date)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'day_judge_%s.json' % date)

    if not os.path.exists(src):
        result = {'date': date, 'ok': False, 'reason': 'NO_CAPTURE_FILE',
                  'suspect': False, 'computed_at': datetime.now().isoformat()}
    else:
        sm = morning_minutes(src)
        n, broken = broken_rate(sm)
        rate = (broken / n * 100.0) if n else None
        # 반등 표본이 너무 적으면 판정 보류(안전측 = 차단 안 함)
        enough = n >= 30
        suspect = bool(enough and rate is not None and rate >= THRESHOLD)
        result = {'date': date, 'ok': True, 'codes': len(sm),
                  'bounces': n, 'broken': broken,
                  'rate': round(rate, 1) if rate is not None else None,
                  'threshold': THRESHOLD, 'enough_sample': enough,
                  'suspect': suspect,
                  'computed_at': datetime.now().isoformat()}

    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:   # BOM 없는 UTF-8 (파이썬 기록)
        json.dump(result, fh, ensure_ascii=False)
    os.replace(tmp, out_path)

    print('[day_judge] %s rate=%s suspect=%s (bounces=%s broken=%s codes=%s) -> %s' % (
        date, result.get('rate'), result.get('suspect'),
        result.get('bounces'), result.get('broken'), result.get('codes'), out_path))


if __name__ == '__main__':
    main()
