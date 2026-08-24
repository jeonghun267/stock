# -*- coding: utf-8 -*-
"""
장세 일지 v1 (감시테스트, 읽기 전용 - 주문/TR 없음)

친구님 승인 2026-08-08: 날 유형(강한날/보통날/하락일) 판정 자료를 매일 1행씩 쌓는다.
입력:  data\high_range_shadow_YYYYMMDD.csv (분당, 고저폭30 - 이미 매일 자동 생성)
출력:  보고서\장세일지_v1.csv (날짜당 1행, 있는 날짜는 재계산 덮어씀 = 여러 번 돌려도 안전)

행 구성:
  [마감 정답]   등락 중앙 / 눌림(-1%~) 건수·중앙깊이·-5%비율 / 저점반등 중앙
               / 하락마디(-4%~) 반등 가짜율 / -4%,-6% 도달 중앙 분수
  [아침 계기판] 09:30까지만 보고 계산 가능한 것: 갭 중앙 / 등락 중앙 / 최대눌림 중앙
               / 깨진반등률(09:25까지 반등 중 09:30까지 신저가로 깨진 비율)
  [잠정 라벨]   하락일: 눌림 중앙깊이>=4% 또는 가짜반등률>=70%
               강한날: 마감 등락 중앙>=+3%  /  나머지: 보통날
               (문턱은 6일 관측 기준 잠정치 - 2달 쌓인 뒤 재도출 예정)

근거 조사: 8/8 눌림깊이·1분대조·하락시간표 3건 (메모리 stockbot-20260808-*)
롤백: 태스크 SAFEPLUS_MARKET_DAY_JOURNAL 비활성화 + 이 파일 삭제
"""
import csv
import glob
import os
from datetime import datetime
from collections import defaultdict

BASE = r'C:\stock_bot'
SRC_GLOB = os.path.join(BASE, 'data', 'high_range_shadow_*.csv')
OUT_PATH = os.path.join(BASE, '보고서', '장세일지_v1.csv')

GAP_SEC = 150          # 분당 자료 공백 판정
EPI_DEPTH = 0.04       # 하락 마디 문턱 -4%
BOUNCE = 1.01          # 반등 문턱 +1%
LABEL_MIN = 10         # 반등 진짜 판정에 필요한 잔여 분
CUT_0930 = 9 * 60 + 30   # 아침 계기판 마감(분)
CUT_0925 = 9 * 60 + 25   # 깨진반등률 분모 마감(판정 여유 5분)

# 잠정 라벨 문턱 (2026-08-08, 6일 관측 기준 - 축적 후 재도출)
TH_FALL_DEPTH = 4.0    # 하락일: 눌림 중앙깊이 %
TH_FALL_FAKE = 70.0    # 하락일: 가짜반등률 %
TH_STRONG_CHG = 3.0    # 강한날: 마감 등락 중앙 %

COLS = ['날짜', '종목수',
        '등락중앙', '눌림건수', '눌림중앙깊이', '눌림5이상비율', '저점반등중앙',
        '반등건수', '가짜반등률', 'm4중앙분', 'm6중앙분',
        '아침_갭중앙', '아침_등락중앙', '아침_최대눌림중앙', '아침_반등수', '아침_깨진반등률',
        '잠정라벨']


def fnum(x, d=None):
    try:
        return float(x)
    except (ValueError, TypeError):
        return d


def med(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load_day(path):
    by_code = defaultdict(list)
    with open(path, encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            cur = fnum(row.get('current'))
            hi = fnum(row.get('high'))
            lo = fnum(row.get('low'))
            pc = fnum(row.get('prev_close'))
            fp = fnum(row.get('first_price'))
            if cur is None or hi is None or lo is None or cur <= 0:
                continue
            try:
                ts = datetime.fromisoformat(row['ts'])
            except (ValueError, KeyError):
                continue
            by_code[row['code']].append(
                {'ts': ts, 'cur': cur, 'hi': hi, 'lo': lo, 'pc': pc, 'fp': fp})
    return {c: sorted(rs, key=lambda r: r['ts'])
            for c, rs in by_code.items() if len(rs) >= 10}


def pullbacks(rows):
    """실행 고점 대비 -1% 이상 눌림 깊이 목록 (8/8 눌림깊이 조사와 같은 정의)"""
    out = []
    cur_high = None
    min_dd = None
    for i, r in enumerate(rows):
        if i > 0 and (r['ts'] - rows[i - 1]['ts']).total_seconds() > GAP_SEC:
            if min_dd is not None and min_dd <= -1.0:
                out.append(-min_dd)
            cur_high = None
            min_dd = None
        if cur_high is None or r['hi'] > cur_high + 1e-9:
            if min_dd is not None and min_dd <= -1.0:
                out.append(-min_dd)
            cur_high = r['hi']
            min_dd = None
            continue
        dd = (r['cur'] / cur_high - 1.0) * 100.0
        min_dd = dd if min_dd is None else min(min_dd, dd)
    if min_dd is not None and min_dd <= -1.0:
        out.append(-min_dd)
    return out


def fall_bounces(rows):
    """하락 마디(-4%~) 안의 +1% 반등 (가짜=신저가 재갱신). 8/8 하락시간표 조사와 같은 정의.
    반환: (반등 [(가짜여부, 반등시각)], 마디별 m4 분수, m6 분수)"""
    bounces = []
    m4s, m6s = [], []
    peak = rows[0]['cur']
    peak_t = rows[0]['ts']
    in_ep = False
    low = None
    pend = None            # 판정 대기 반등 시각
    m6_done = False

    def finish(recovered, last_ts):
        nonlocal pend
        if pend is not None:
            if recovered or (last_ts - pend).total_seconds() / 60 >= LABEL_MIN:
                bounces.append((0, pend))
            pend = None

    prev_ts = rows[0]['ts']
    for r in rows:
        ts, cur = r['ts'], r['cur']
        if (ts - prev_ts).total_seconds() > GAP_SEC:
            if in_ep:
                finish(False, prev_ts)
            in_ep = False
            peak, peak_t = cur, ts
            prev_ts = ts
            continue
        prev_ts = ts
        if not in_ep:
            if cur > peak:
                peak, peak_t = cur, ts
            elif (peak - cur) / peak >= EPI_DEPTH:
                in_ep = True
                low = cur
                m4s.append((ts - peak_t).total_seconds() / 60)
                m6_done = False
        else:
            depth = (peak - cur) / peak * 100
            if depth >= 6 and not m6_done:
                m6s.append((ts - peak_t).total_seconds() / 60)
                m6_done = True
            if cur < low:
                if pend is not None:
                    bounces.append((1, pend))   # 반등 뒤 신저가 = 가짜
                    pend = None
                low = cur
            elif pend is None and cur >= low * BOUNCE:
                pend = ts
            if cur >= peak:
                finish(True, ts)
                in_ep = False
                peak, peak_t = cur, ts
    if in_ep:
        finish(False, rows[-1]['ts'])
    return bounces, m4s, m6s


def day_row(date, day):
    chg, gaps, chg0930, mdd0930 = [], [], [], []
    all_pb, all_reb = [], []
    all_bn, all_m4, all_m6 = [], [], []
    bn0930_n = 0
    bn0930_broken = 0

    for rows in day.values():
        pc = rows[0]['pc']
        if pc:
            chg.append((rows[-1]['cur'] / pc - 1) * 100)
            if rows[0]['fp']:
                gaps.append((rows[0]['fp'] / pc - 1) * 100)
        all_pb.extend(pullbacks(rows))

        day_lo = min(r['lo'] for r in rows)
        idx = next(i for i, r in enumerate(rows) if r['lo'] <= day_lo * 1.0001)
        best = max((r['cur'] for r in rows[idx:]), default=day_lo)
        all_reb.append((best / day_lo - 1) * 100)

        bn, m4, m6 = fall_bounces(rows)
        all_bn.extend(bn)
        all_m4.extend(m4)
        all_m6.extend(m6)

        am = [r for r in rows if r['ts'].hour * 60 + r['ts'].minute <= CUT_0930]
        if am:
            if pc:
                chg0930.append((am[-1]['cur'] / pc - 1) * 100)
            mdd0930.append(max((r['hi'] - r['cur']) / r['hi'] * 100 for r in am))
            bn_am, _, _ = fall_bounces(am)
            for fake, ts in bn_am:
                if ts.hour * 60 + ts.minute <= CUT_0925:
                    bn0930_n += 1
                    if fake:
                        bn0930_broken += 1

    fake_rate = (sum(f for f, _ in all_bn) / len(all_bn) * 100) if all_bn else None
    depth_med = med(all_pb)
    chg_med = med(chg)

    if depth_med is not None and fake_rate is not None and (
            depth_med >= TH_FALL_DEPTH or fake_rate >= TH_FALL_FAKE):
        label = '하락일'
    elif chg_med is not None and chg_med >= TH_STRONG_CHG:
        label = '강한날'
    else:
        label = '보통날'

    def f(v, nd=2):
        return '' if v is None else round(v, nd)

    return {
        '날짜': date, '종목수': len(day),
        '등락중앙': f(chg_med), '눌림건수': len(all_pb),
        '눌림중앙깊이': f(depth_med),
        '눌림5이상비율': f(sum(1 for d in all_pb if d >= 5) / len(all_pb) * 100, 1) if all_pb else '',
        '저점반등중앙': f(med(all_reb)),
        '반등건수': len(all_bn), '가짜반등률': f(fake_rate, 1),
        'm4중앙분': f(med(all_m4), 0), 'm6중앙분': f(med(all_m6), 0),
        '아침_갭중앙': f(med(gaps)), '아침_등락중앙': f(med(chg0930)),
        '아침_최대눌림중앙': f(med(mdd0930)),
        '아침_반등수': bn0930_n,
        '아침_깨진반등률': f(bn0930_broken / bn0930_n * 100, 1) if bn0930_n else '',
        '잠정라벨': label,
    }


def main():
    ledger = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding='utf-8-sig', newline='') as fh:
            for row in csv.DictReader(fh):
                if row.get('날짜'):
                    ledger[row['날짜']] = row

    files = sorted(glob.glob(SRC_GLOB))
    done = 0
    for path in files:
        date = os.path.basename(path)[-12:-4]
        day = load_day(path)
        if not day:
            continue
        ledger[date] = day_row(date, day)
        done += 1

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction='ignore')
        w.writeheader()
        for date in sorted(ledger):
            w.writerow(ledger[date])

    last = ledger[sorted(ledger)[-1]] if ledger else {}
    print('[market_day_journal] %s: 원천 %d일 재계산, 일지 %d행, 최근=%s %s' % (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'), done, len(ledger),
        last.get('날짜', '-'), last.get('잠정라벨', '-')))


if __name__ == '__main__':
    main()
