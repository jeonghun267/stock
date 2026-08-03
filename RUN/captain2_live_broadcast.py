# -*- coding: utf-8 -*-
"""
실전 중계방송 — 09:00부터 1분마다 예약태스크가 호출.
읽기 전용: 엔진들이 이미 쓰는 파일만 읽는다. 키움 TR 직접조회 0건.
  - LOG/fills_YYYYMMDD.csv       : 전 엔진 실체결(진실)
  - data/captain2_state.json     : 캡틴2 보유/현재가/심장박동
절대 크래시하지 않는다(중계가 죽으면 안 됨). 모든 읽기는 try/except.
출력:
  - 바탕화면\캡틴2_중계.txt        : 1분마다 덮어쓰는 실시간 현황판
  - 바탕화면\캡틴2_중계_기록.txt   : 1분당 1줄 누적 로그(중계 기록)
"""
import os, csv, json, datetime, collections

BASE     = r"C:\stock_bot"
DESKTOP  = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\UserK"), "Desktop")
SNAP     = os.path.join(DESKTOP, "캡틴2_중계.txt")
SNAP_HTML = os.path.join(DESKTOP, "캡틴2_중계.html")
TAPE     = os.path.join(DESKTOP, "캡틴2_중계_기록.txt")
STATE_JS = os.path.join(BASE, "data", "captain2_state.json")
FLAG_DIR = os.path.join(BASE, "config")
HELD_PHASES = {"HOLD", "WATCH", "BUY_PENDING", "SELL_PENDING", "RECOVERY_HOLD"}


def _now():
    return datetime.datetime.now()


def _fmt(n):
    try:
        return f"{n:,.0f}"
    except Exception:
        return str(n)


def load_state():
    """캡틴2 상태 — (요약dict, 코드→이름맵). 실패해도 빈 값."""
    info = {"ok": False, "ts": None, "age": None, "live": None,
            "entries_today": None, "held": []}
    names = {}
    try:
        d = json.load(open(STATE_JS, encoding="utf-8"))
    except Exception as e:
        info["err"] = str(e)
        return info, names
    info["live"] = d.get("live")
    info["entries_today"] = d.get("entries_today")
    ts = d.get("ts")
    info["ts"] = ts
    try:
        t = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        info["age"] = (_now() - t).total_seconds()
    except Exception:
        info["age"] = None
    st = d.get("states", {}) or {}
    for code, s in st.items():
        nm = s.get("name")
        if nm:
            names[code] = nm
        try:
            if s.get("phase") in HELD_PHASES and (s.get("qty") or 0) > 0 and not s.get("exit_ts"):
                ep = float(s.get("entry_price") or 0)
                rp = s.get("recent_prices") or []
                cur = float(rp[-1][1]) if rp else ep
                pk = float(s.get("peak_price") or cur)
                pnl = (cur / ep - 1) * 100 if ep else 0.0
                pkp = (pk / ep - 1) * 100 if ep else 0.0
                info["held"].append({
                    "code": code, "name": nm or code, "entry": ep,
                    "cur": cur, "pnl": pnl, "peak_pnl": pkp,
                    "grade": s.get("money_size_grade"), "lane": s.get("lane"),
                    "phase": s.get("phase"),
                })
        except Exception:
            continue
    info["held"].sort(key=lambda x: x["pnl"], reverse=True)
    info["ok"] = True
    return info, names


def load_fills(names):
    """오늘 전 엔진 실체결 요약. 개장 전이면 파일 없음."""
    res = {"ok": False, "buys": 0, "sells": 0, "realized": 0.0,
           "net": [], "events": [], "bycode": [], "roundtrips": []}
    day = _now().strftime("%Y%m%d")
    path = os.path.join(BASE, "LOG", f"fills_{day}.csv")
    if not os.path.exists(path):
        res["reason"] = "개장전(체결파일 없음)"
        return res
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                if r.get("state") != "체결":
                    continue
                rows.append(r)
    except Exception as e:
        res["reason"] = f"읽기실패:{e}"
        return res
    # FIFO 페어링(종목별) — 실현손익 + 순보유 + 종목별 집계(오늘 매수 종목 전체)
    q = collections.defaultdict(collections.deque)   # code -> deque of (px, qty)
    realized = 0.0
    # 종목별 집계: 매수건수/매도건수/실현손익/마지막 매수가/첫 매수시각
    agg = collections.OrderedDict()   # 매수 발생 순서 유지
    def _slot(code):
        if code not in agg:
            agg[code] = {"code": code, "name": names.get(code, code),
                         "buys": 0, "sells": 0, "realized": 0.0,
                         "last_buy": 0.0, "first_ts": (rows and "") or "", "netqty": 0}
        agg[code]["name"] = names.get(code, agg[code]["name"])
        return agg[code]
    for r in rows:
        code = r.get("code", "")
        try:
            qty = int(r.get("fill_qty") or 0)
            px = float(r.get("fill_px") or 0)
        except Exception:
            continue
        buy = "매수" in (r.get("otype") or "")
        ts_hms = (r.get("ts") or "")[11:19]
        a = _slot(code)
        if buy:
            res["buys"] += 1
            a["buys"] += 1
            a["last_buy"] = px
            if not a["first_ts"]:
                a["first_ts"] = ts_hms
            a["netqty"] += qty
            q[code].append([px, qty, ts_hms])   # 매수시각 동봉(왕복 시간표용)
        else:
            res["sells"] += 1
            a["sells"] += 1
            a["netqty"] -= qty
            remain = qty
            while remain > 0 and q[code]:
                bpx, bq, bts = q[code][0]
                m = min(bq, remain)
                gain = (px - bpx) * m
                realized += gain
                a["realized"] += gain
                # ★[매수/매도 시간표] 왕복 1건 기록(매수시각→매도시각·손익%)
                res["roundtrips"].append({
                    "buy_ts": bts, "sell_ts": ts_hms, "code": code,
                    "name": names.get(code, code), "bpx": bpx, "spx": px,
                    "pnl": (px / bpx - 1) * 100 if bpx else 0.0})
                bq -= m
                remain -= m
                if bq <= 0:
                    q[code].popleft()
                else:
                    q[code][0][0] = bpx
                    q[code][0][1] = bq
    res["realized"] = realized
    for code, dq in q.items():
        nq = sum(x[1] for x in dq)
        if nq > 0:
            res["net"].append({"code": code, "name": names.get(code, code), "qty": nq})
    res["bycode"] = list(agg.values())
    # 최근 이벤트(마지막 8건)
    for r in rows[-8:]:
        t = (r.get("ts") or "")[11:19]
        code = r.get("code", "")
        side = "매수" if "매수" in (r.get("otype") or "") else "매도"
        res["events"].append(f"  {t}  {side}  {names.get(code, code)}({code})  {_fmt(r.get('fill_px'))}")
    res["ok"] = True
    return res


def load_valley():
    """골짜기(valley_hunter) 오늘 매매 — 자체 CSV(진입출처·수익%까지 보유). 실패해도 빈 값."""
    res = {"ok": False, "trades": [], "open": [], "wins": 0, "losses": 0, "sum": 0.0}
    day = _now().strftime("%Y%m%d")
    path = os.path.join(BASE, "LOG", "valley_hunter_live.csv")
    rows = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            rd = csv.reader(f); next(rd, None)
            for r in rd:
                if len(r) >= 21 and r[0] == day:
                    rows.append(r)
    except Exception as e:
        res["reason"] = f"읽기실패:{e}"
        return res
    if not rows:
        res["reason"] = "오늘 골짜기 매매 없음"
        return res
    def src(s):
        return {"BASE_BREAKOUT": "베이스돌파"}.get(s, s or "?")
    openpos = {}
    for r in rows:
        code, name, direction, reason, pnl, source, t = r[2], r[3], r[4], r[5], r[12], r[20], r[1]
        if direction == "BUY":
            openpos[code] = (name, t, src(source))
        elif direction == "SELL":
            try:
                p = float(pnl or 0)
            except Exception:
                p = 0.0
            b = openpos.pop(code, (name, "", src(source)))
            res["trades"].append({"code": code, "name": name, "src": b[2],
                                  "pnl": p, "reason": reason})
            res["sum"] += p
            if p > 0:
                res["wins"] += 1
            elif p < 0:
                res["losses"] += 1
    for code, (name, t, s) in openpos.items():
        res["open"].append({"code": code, "name": name, "src": s})
    res["ok"] = True
    return res


def load_captain_pnl():
    """캡틴2 오늘 매도 손익% — 자체 로그(INFO SELL … | <pnl>%) 파싱. 승패·합계."""
    res = {"trades": [], "wins": 0, "losses": 0, "sum": 0.0, "ok": False}
    day = _now().strftime("%Y-%m-%d")
    path = os.path.join(BASE, "LOG", "captain2_moneyflow.log")
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return res
    for ln in txt.splitlines():
        if not (ln.startswith(f"[{day}") and "INFO SELL " in ln):
            continue
        try:
            body = ln.split("INFO SELL ", 1)[1]
            parts = body.split("|")
            head = parts[0].split()          # name code @px
            name, code = head[0], head[1]
            pnl = float(parts[-1].strip().replace("%", ""))
        except Exception:
            continue
        res["trades"].append({"code": code, "name": name, "pnl": pnl})
        res["sum"] += pnl
        if pnl > 0:
            res["wins"] += 1
        elif pnl < 0:
            res["losses"] += 1
    res["ok"] = True
    return res


def load_sources():
    """종목→출처 라벨 맵. 캡틴2 이벤트 + 골짜기 CSV에서 읽어 [캡틴]/[베이스]/[급락]으로 구분.
    한 종목을 두 엔진이 사면 둘 다 표기(예: 캡틴·베이스)."""
    day = _now().strftime("%Y%m%d")
    smap = {}   # code -> set(라벨)

    def add(code, lab):
        smap.setdefault(code, set()).add(lab)
    # 캡틴2 (자체 이벤트 CSV의 BUY)
    try:
        p = os.path.join(BASE, "data", "shadow", f"captain2_events_{day}.csv")
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            rd = csv.reader(f); next(rd, None)
            for r in rd:
                if len(r) >= 4 and r[3] == "BUY":
                    add(r[1], "캡틴")
    except Exception:
        pass
    # 골짜기 (자체 CSV의 BUY, 진입출처로 베이스/급락 구분)
    try:
        p = os.path.join(BASE, "LOG", "valley_hunter_live.csv")
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            rd = csv.reader(f); next(rd, None)
            for r in rd:
                if len(r) >= 21 and r[0] == day and r[4] == "BUY":
                    s = (r[20] or "").upper()
                    lab = "베이스" if "BASE" in s else ("급락" if ("CRASH" in s or "급락" in s) else ("골짜기:" + (r[20] or "?")))
                    add(r[2], lab)
    except Exception:
        pass
    return {c: "·".join(sorted(v)) for c, v in smap.items()}


def flags():
    out = []
    for fn, label in (("manual_buy_block.flag", "전면매수차단"),
                      ("captain2_off.flag", "캡틴2정지"),
                      ("valley_off.flag", "골짜기정지")):
        if os.path.exists(os.path.join(FLAG_DIR, fn)):
            out.append(label)
    return out


def _src_summary(cap, vly):
    """출처별 성적 — [캡틴, 베이스, 급락] 각 (매매수, 승, 패, 합계%). 데이터 없으면 0."""
    out = collections.OrderedDict((k, {"n": 0, "w": 0, "l": 0, "sum": 0.0}) for k in ("캡틴", "베이스", "급락"))
    for t in (cap.get("trades") or []):
        g = out["캡틴"]; g["n"] += 1; g["sum"] += t["pnl"]
        g["w"] += t["pnl"] > 0; g["l"] += t["pnl"] < 0
    for t in (vly.get("trades") or []):
        s = t.get("src", "")
        key = "베이스" if ("베이스" in s or "BASE" in s.upper()) else ("급락" if ("급락" in s or "CRASH" in s.upper()) else None)
        if key is None:
            continue
        g = out[key]; g["n"] += 1; g["sum"] += t["pnl"]
        g["w"] += t["pnl"] > 0; g["l"] += t["pnl"] < 0
    return out


def build():
    now = _now()
    st, names = load_state()
    fl = load_fills(names)
    vly = load_valley()
    cap = load_captain_pnl()
    srcmap = load_sources()
    if fl.get("ok"):
        for b in fl["bycode"]:
            b["srclabel"] = srcmap.get(b["code"], "?")
    summ = _src_summary(cap, vly)
    kf = flags()
    L = []
    L.append("=" * 46)
    wd = "월화수목금토일"[now.weekday()]
    L.append(f"  📻 실전 중계   {now.strftime('%m-%d')}({wd}) {now.strftime('%H:%M:%S')}")
    L.append("=" * 46)
    L.append("")

    # 엔진 상태
    L.append("[엔진 상태]")
    if st["ok"]:
        age = st["age"]
        if age is None:
            hb = "심장박동 ?"
        elif age <= 15:
            hb = f"정상 ✅ ({age:.0f}초전)"
        elif age <= 90:
            hb = f"느림 ⚠️ ({age:.0f}초전)"
        else:
            hb = f"멈춤 의심 🔴 ({age/60:.0f}분전)"
        mode = "LIVE" if st["live"] else "SHADOW"
        L.append(f"  캡틴2  {mode}  {hb}   오늘진입 {st['entries_today']}건")
    else:
        L.append(f"  캡틴2  상태파일 못읽음 ({st.get('err','?')})")
    L.append(f"  킬스위치: {'  '.join(kf) if kf else '없음(정상)'}")
    L.append("")

    # 오늘 실전 체결(전 엔진)
    L.append("[오늘 실전 체결 — 전 엔진]")
    if fl["ok"]:
        sign = "+" if fl["realized"] >= 0 else ""
        L.append(f"  매수 {fl['buys']}건 / 매도 {fl['sells']}건")
        L.append(f"  실현손익(체결기준): {sign}{_fmt(fl['realized'])}원")
        if fl["net"]:
            names_s = ", ".join(f"{x['name']}×{x['qty']}" for x in fl["net"])
            L.append(f"  현재 순보유: {len(fl['net'])}종목  ({names_s})")
        else:
            L.append("  현재 순보유: 없음")
    else:
        L.append(f"  {fl.get('reason','대기중')}")
    L.append("")

    # 출처별 성적 — 뭐가 이겼나 졌나(캡틴/베이스/급락)
    L.append("[출처별 성적 — 캡틴 / 베이스 / 급락]")
    for k, g in summ.items():
        if g["n"] == 0:
            L.append(f"  {k:<4} 미발생")
        else:
            sign = "+" if g["sum"] >= 0 else ""
            L.append(f"  {k:<4} {g['n']}매매  {g['w']}승 {g['l']}패  합계 {sign}{g['sum']:.2f}%")
    L.append("")

    # 오늘 매수 종목 — 전 엔진(출처 라벨·종목번호·익절/손절)
    L.append("[오늘 매수 종목 — 전 엔진]")
    if fl["ok"] and fl["bycode"]:
        for b in fl["bycode"]:
            rz = b["realized"]
            if b["sells"] == 0:
                res_txt = "보유중(미실현)"
            elif rz > 0:
                res_txt = f"익절 +{_fmt(rz)}원"
            elif rz < 0:
                res_txt = f"손절 {_fmt(rz)}원"
            else:
                res_txt = "본전"
            hold = f"  보유{b['netqty']}주" if b["netqty"] > 0 else "  청산"
            L.append(f"  [{b.get('srclabel','?')}] {b['name']:<9}({b['code']})  "
                     f"매수{b['buys']}·매도{b['sells']}  {res_txt}{hold}")
    elif fl["ok"]:
        L.append("  오늘 매수 없음")
    else:
        L.append("  대기중")
    L.append("")

    # 캡틴2 보유 상세
    L.append("[캡틴2 보유 상세]")
    if st["ok"] and st["held"]:
        for h in st["held"]:
            sign = "+" if h["pnl"] >= 0 else ""
            L.append(f"  {h['name']:<10}({h['code']}) 진입 {_fmt(h['entry'])} → 현재 {_fmt(h['cur'])}"
                     f"  {sign}{h['pnl']:.2f}%  (최고 +{h['peak_pnl']:.2f}%)")
    elif st["ok"]:
        L.append("  보유 없음")
    else:
        L.append("  -")
    L.append("")

    # 골짜기 오늘 매매 (진입출처·손익)
    L.append("[골짜기 오늘 매매]")
    if vly["ok"]:
        for tr in vly["trades"]:
            sign = "+" if tr["pnl"] >= 0 else ""
            rt = "익절" if tr["pnl"] > 0 else ("손절" if tr["pnl"] < 0 else "본전")
            L.append(f"  {tr['name']:<9}({tr['code']}) {tr['src']}  {sign}{tr['pnl']:.2f}% {rt} [{tr['reason']}]")
        for op in vly["open"]:
            L.append(f"  {op['name']:<9}({op['code']}) {op['src']}  보유중")
        sign = "+" if vly["sum"] >= 0 else ""
        L.append(f"  → {len(vly['trades'])}매매 {vly['wins']}승 {vly['losses']}패 · 합계 {sign}{vly['sum']:.2f}%")
    else:
        L.append(f"  {vly.get('reason','대기중')}")
    L.append("")

    # 매수/매도 시간표 (왕복별 매수시각→매도시각·손익)
    L.append("[매수·매도 시간표]")
    if fl["ok"] and fl["roundtrips"]:
        for t in fl["roundtrips"]:
            sign = "+" if t["pnl"] >= 0 else ""
            L.append(f"  매수 {t['buy_ts']} → 매도 {t['sell_ts']}  {t['name']:<9}({t['code']})  "
                     f"{_fmt(t['bpx'])}→{_fmt(t['spx'])}  {sign}{t['pnl']:.2f}%")
    elif fl["ok"] and fl["net"]:
        L.append("  (완결 매매 없음 — 보유 중)")
    else:
        L.append("  -")
    L.append("")

    # 최근 이벤트
    L.append("[최근 체결 이벤트]")
    if fl["ok"] and fl["events"]:
        L.extend(fl["events"])
    else:
        L.append("  -")
    L.append("")
    return "\n".join(L), (st, fl, vly, summ, kf, now)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(st, fl, vly, summ, kf, now):
    """검정 배경 다크테마 HTML — 브라우저로 열면 눈부심 적고 20초마다 자동 새로고침."""
    wd = "월화수목금토일"[now.weekday()]
    P = []   # 본문 조각
    P.append(f'<div class="clock">{now.strftime("%m-%d")}({wd}) '
             f'<b>{now.strftime("%H:%M:%S")}</b></div>')

    # 엔진 상태
    P.append('<h2>엔진 상태</h2>')
    if st and st.get("ok"):
        age = st["age"]
        if age is None:
            hb, cls = "심장박동 ?", "warn"
        elif age <= 15:
            hb, cls = f"정상 ({age:.0f}초전)", "up"
        elif age <= 90:
            hb, cls = f"느림 ({age:.0f}초전)", "warn"
        else:
            hb, cls = f"멈춤 의심 ({age/60:.0f}분전)", "down"
        mode = "LIVE" if st["live"] else "SHADOW"
        mcls = "up" if st["live"] else "warn"
        P.append(f'<div class="row">캡틴2 <span class="badge {mcls}">{mode}</span> '
                 f'<span class="{cls}">{hb}</span> &nbsp; 오늘진입 <b>{st["entries_today"]}</b>건</div>')
    else:
        P.append('<div class="row down">캡틴2 상태파일 못읽음</div>')
    if kf:
        P.append(f'<div class="row down">킬스위치: {_esc("  ".join(kf))}</div>')
    else:
        P.append('<div class="row dim">킬스위치: 없음(정상)</div>')

    # 오늘 실전 체결
    P.append('<h2>오늘 실전 체결 — 전 엔진</h2>')
    if fl and fl.get("ok"):
        rcls = "up" if fl["realized"] >= 0 else "down"
        sign = "+" if fl["realized"] >= 0 else ""
        P.append(f'<div class="row">매수 <b>{fl["buys"]}</b>건 / 매도 <b>{fl["sells"]}</b>건</div>')
        P.append(f'<div class="row">실현손익(체결기준): '
                 f'<span class="big {rcls}">{sign}{_fmt(fl["realized"])}원</span></div>')
        if fl["net"]:
            names_s = ", ".join(f'{_esc(x["name"])}({_esc(x["code"])})×{x["qty"]}' for x in fl["net"])
            P.append(f'<div class="row">현재 순보유: {len(fl["net"])}종목 &nbsp;<span class="dim">({names_s})</span></div>')
        else:
            P.append('<div class="row dim">현재 순보유: 없음</div>')
    else:
        P.append(f'<div class="row dim">{_esc(fl.get("reason", "대기중") if fl else "대기중")}</div>')

    # 출처별 성적 — 캡틴 / 베이스 / 급락 (뭐가 이겼나 졌나)
    P.append('<h2>출처별 성적 — 캡틴 / 베이스 / 급락</h2>')
    if summ:
        P.append('<table>')
        for k, g in summ.items():
            if g["n"] == 0:
                P.append(f'<tr><td class="nm">{k}</td><td class="dim" colspan="3">미발생</td></tr>')
            else:
                scls = "up" if g["sum"] >= 0 else "down"
                sign = "+" if g["sum"] >= 0 else ""
                P.append(f'<tr><td class="nm">{k}</td>'
                         f'<td>{g["n"]}매매</td>'
                         f'<td><span class="up">{g["w"]}승</span> <span class="down">{g["l"]}패</span></td>'
                         f'<td class="{scls} big">{sign}{g["sum"]:.2f}%</td></tr>')
        P.append('</table>')

    # 오늘 매수 종목 — 전 엔진(출처 라벨·종목번호·익절/손절)
    P.append('<h2>오늘 매수 종목 — 전 엔진 (출처 · 익절/손절)</h2>')
    if fl and fl.get("ok") and fl["bycode"]:
        P.append('<table>')
        for b in fl["bycode"]:
            rz = b["realized"]
            if b["sells"] == 0:
                res_cls, res_txt = "warn", "보유중(미실현)"
            elif rz > 0:
                res_cls, res_txt = "up", f'익절 +{_fmt(rz)}원'
            elif rz < 0:
                res_cls, res_txt = "down", f'손절 {_fmt(rz)}원'
            else:
                res_cls, res_txt = "dim", "본전"
            hold = f'<td class="warn">보유 {b["netqty"]}주</td>' if b["netqty"] > 0 else '<td class="dim">청산</td>'
            P.append(f'<tr><td class="badge warn">{_esc(b.get("srclabel","?"))}</td>'
                     f'<td class="nm">{_esc(b["name"])}</td>'
                     f'<td class="dim">{_esc(b["code"])}</td>'
                     f'<td>매수{b["buys"]}·매도{b["sells"]}</td>'
                     f'<td class="{res_cls} big">{res_txt}</td>'
                     f'{hold}</tr>')
        P.append('</table>')
    elif fl and fl.get("ok"):
        P.append('<div class="row dim">오늘 매수 없음</div>')
    else:
        P.append('<div class="row dim">대기중</div>')

    # 골짜기 오늘 매매(진입출처·손익)
    P.append('<h2>골짜기 오늘 매매 (베이스 / 급락)</h2>')
    if vly and vly.get("ok"):
        P.append('<table>')
        for tr in vly["trades"]:
            pcls = "up" if tr["pnl"] >= 0 else "down"
            sign = "+" if tr["pnl"] >= 0 else ""
            P.append(f'<tr><td class="badge warn">{_esc(tr["src"])}</td>'
                     f'<td class="nm">{_esc(tr["name"])}</td><td class="dim">{_esc(tr["code"])}</td>'
                     f'<td class="{pcls} big">{sign}{tr["pnl"]:.2f}%</td>'
                     f'<td class="dim">{_esc(tr["reason"])}</td></tr>')
        for op in vly["open"]:
            P.append(f'<tr><td class="badge warn">{_esc(op["src"])}</td>'
                     f'<td class="nm">{_esc(op["name"])}</td><td class="dim">{_esc(op["code"])}</td>'
                     f'<td class="warn">보유중</td><td></td></tr>')
        P.append('</table>')
        sign = "+" if vly["sum"] >= 0 else ""
        P.append(f'<div class="row dim">{len(vly["trades"])}매매 {vly["wins"]}승 {vly["losses"]}패 · 합계 {sign}{vly["sum"]:.2f}%</div>')
    else:
        P.append(f'<div class="row dim">{_esc(vly.get("reason","대기중") if vly else "대기중")}</div>')

    # 캡틴2 보유 상세
    P.append('<h2>캡틴2 보유 상세</h2>')
    if st and st.get("ok") and st["held"]:
        P.append('<table>')
        for h in st["held"]:
            pcls = "up" if h["pnl"] >= 0 else "down"
            sign = "+" if h["pnl"] >= 0 else ""
            P.append(f'<tr><td class="nm">{_esc(h["name"])}</td>'
                     f'<td class="dim">{_esc(h["code"])}</td>'
                     f'<td>{_fmt(h["entry"])}</td><td>→</td><td>{_fmt(h["cur"])}</td>'
                     f'<td class="{pcls} big">{sign}{h["pnl"]:.2f}%</td>'
                     f'<td class="dim">최고 +{h["peak_pnl"]:.2f}%</td></tr>')
        P.append('</table>')
    elif st and st.get("ok"):
        P.append('<div class="row dim">보유 없음</div>')
    else:
        P.append('<div class="row dim">-</div>')

    # 매수/매도 시간표 (왕복별)
    P.append('<h2>매수·매도 시간표 (매수시각 → 매도시각 · 손익)</h2>')
    if fl and fl.get("ok") and fl["roundtrips"]:
        P.append('<table>')
        for t in fl["roundtrips"]:
            pcls = "up" if t["pnl"] >= 0 else "down"
            sign = "+" if t["pnl"] >= 0 else ""
            P.append(f'<tr><td class="dim">{_esc(t["buy_ts"])}</td><td class="dim">→</td>'
                     f'<td class="dim">{_esc(t["sell_ts"])}</td>'
                     f'<td class="nm">{_esc(t["name"])}</td><td class="dim">{_esc(t["code"])}</td>'
                     f'<td class="dim">{_fmt(t["bpx"])}→{_fmt(t["spx"])}</td>'
                     f'<td class="{pcls} big">{sign}{t["pnl"]:.2f}%</td></tr>')
        P.append('</table>')
    elif fl and fl.get("ok"):
        P.append('<div class="row dim">완결 매매 없음(보유 중 또는 대기)</div>')
    else:
        P.append('<div class="row dim">-</div>')

    # 최근 이벤트
    P.append('<h2>최근 체결 이벤트</h2>')
    if fl and fl.get("ok") and fl["events"]:
        P.append('<div class="events">')
        for e in fl["events"]:
            parts = e.split()
            cls = "up" if "매수" in e else "down"
            P.append(f'<div class="ev {cls}">{_esc(e.strip())}</div>')
        P.append('</div>')
    else:
        P.append('<div class="row dim">-</div>')

    body = "\n".join(P)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="20">
<title>실전 중계</title>
<style>
  html,body{{margin:0;background:#000;color:#e2e2e2;
    font-family:'Consolas','D2Coding','Malgun Gothic',monospace;font-size:19px;line-height:1.65;}}
  .wrap{{max-width:820px;margin:0 auto;padding:22px 26px 60px;}}
  .clock{{font-size:26px;color:#bbb;border-bottom:1px solid #333;padding-bottom:10px;margin-bottom:6px;}}
  .clock b{{color:#fff;}}
  h2{{font-size:15px;color:#7fb2ff;margin:22px 0 6px;font-weight:600;letter-spacing:.5px;}}
  .row{{margin:3px 0;}}
  .up{{color:#3ddc84;}} .down{{color:#ff6b6b;}} .warn{{color:#ffcf5c;}} .dim{{color:#8a8a8a;}}
  .big{{font-size:22px;font-weight:700;}}
  .badge{{padding:1px 9px;border-radius:5px;font-weight:700;font-size:15px;}}
  .badge.up{{background:#12351f;color:#3ddc84;}} .badge.warn{{background:#3a2f10;color:#ffcf5c;}}
  table{{border-collapse:collapse;margin-top:4px;}}
  td{{padding:3px 12px 3px 0;white-space:nowrap;}}
  td.nm{{color:#fff;min-width:110px;}}
  .events .ev{{margin:2px 0;font-size:17px;}}
</style></head>
<body><div class="wrap">
{body}
</div></body></html>"""


def main():
    now = _now()
    kf = []
    st = fl = vly = summ = None      # ★예외경로에서도 정의(백지 방지)
    try:
        text, (st, fl, vly, summ, kf, now) = build()
    except Exception as e:
        text = f"[중계 생성 오류] {e}"
    # [2026-07-23 친구님] 흰색 txt 현황판 폐지 — 다크 HTML만 유지(기록 파일은 존치).
    # ★[백지 방지 2026-07-23] HTML 문자열을 먼저 만들고 '성공할 때만' 파일에 쓴다.
    #   (open("w")가 먼저 파일을 비운 뒤 render가 실패하면 빈 백지가 남던 버그 수정)
    try:
        html = render_html(st, fl, vly, summ, kf, now)
        with open(SNAP_HTML, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass
    # 기록: 1분당 1줄
    try:
        if fl and fl.get("ok"):
            sign = "+" if fl["realized"] >= 0 else ""
            held = len(st["held"]) if (st and st.get("ok")) else "?"
            line = (f"{now.strftime('%H:%M')} | 매수 {fl['buys']} 매도 {fl['sells']} | "
                    f"실현 {sign}{_fmt(fl['realized'])}원 | 캡틴2보유 {held}"
                    f"{'  [KILL:'+','.join(kf)+']' if kf else ''}\n")
            with open(TAPE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
    print(text)


if __name__ == "__main__":
    main()
