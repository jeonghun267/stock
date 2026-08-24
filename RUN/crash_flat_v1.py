# -*- coding: utf-8 -*-
"""🛟 FLAT 청산 안전판(최후 보루) — 엔진이 죽어도 보유 포지션 확실히 정리  [2026-07-16 신설]

친구님 "09:20 FLAT 안전판 해줘." 급락주·아침대장 엔진이 09:20 청산을 못 하고 죽으면(캡틴 55초 사망 전례)
보유 포지션이 방치된다. 이 별도 태스크가 두 전략 장부의 보유(pos=True) 종목을 전량 시장가 매도.
  · 엔진이 살아서 이미 청산했으면 pos=False → 안 팜(중복 방지). 매도 성공 시 장부도 pos=False로 되적음.
  · 매도라 주문 관문(매수 화이트리스트)을 안 탐. rqname 접두어는 각 전략 것 유지.
  · FLAT_LIVE=NO면 그림자(주문0). 창 09:24~09:35.
  · ★[7/16 수술] 09:21→09:24 — 본 엔진(~09:21:30)·전략별 FLAT(09:22/09:23)이 다 끝난 뒤 마지막에 돈다(겹침·이중매도 제거).

★[7/16 친구님 승인 ㉯ — 계좌 대조 2차 패스] 장부 기반의 사각 = '매도 유령'(매도 접수OK·체결0인데
  장부는 팔림 → pos=False라 어떤 안전판에도 안 걸리고 오버나잇. 기가레인 매도 "[800033] 0주" 패턴).
  → 장부 패스 후: 오늘 fills CSV(게이트웨이 체결 직기록)에서 종목별 순잔량(매수체결-매도체결)을 계산,
    순잔량>0 이면 키움 잔고(opw00018)의 '매매가능수량'과 대조해 min(순잔량, 매매가능)을 청산.
  · 기존 보유(원익IPS 1주 등)는 오늘 순잔량에 안 잡힘 = 절대 안 팜. 매매가능수량 캡 = 걸려있는 매도주문과 이중매도 방지.
  · 아침(09:24 전) 이 계좌의 매수는 두 전략뿐(ONLY_MF_ALLOW) — 수동 아침매수는 하지 말 것(하면 같이 청산됨).
  · 끄기 = FLAT_ACCT=NO.
"""
import os, sys, csv, json, time, uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, r"C:\stock_bot\RUN")

LEDGERS = [(r"C:\stock_bot\data\crash_flow_live_ledger.json", "CRASHFLOW"),
           (r"C:\stock_bot\data\captain_live_ledger.json", "MFLOWCAP")]
LOG = Path(r"C:\stock_bot\data\LOG\crash_flat.log")
FILLS_DIR = Path(r"C:\stock_bot\LOG")
LIVE  = os.environ.get("FLAT_LIVE", "YES").strip().upper() == "YES"
ACCT  = os.environ.get("FLAT_ACCT", "YES").strip().upper() == "YES"
START = os.environ.get("FLAT_START", "0924")
END   = os.environ.get("FLAT_END", "0935")


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {m}\n")
    except Exception:
        pass
    print(m, flush=True)


def _connect():
    """브로커 연결 — (bc, 계좌) 또는 (None, "")."""
    try:
        from broker_client import BrokerClient, is_broker_alive
        if not is_broker_alive():
            _log("🚨 브로커 죽음 → FLAT 청산 불가(수동 확인 필요)"); return None, ""
        bc = BrokerClient()
        ai = bc.account_info("ACCNO")
        accs = (ai.get("data") or {}).get("accounts") or (ai.get("data") or {}).get("ACCNO") or []
        if isinstance(accs, str):
            accs = [a for a in accs.split(";") if a]
        acc = (accs[0] if isinstance(accs, list) and accs else "") \
            or os.environ.get("SAFEPLUS_ACCOUNT", "").strip()
        if not acc:
            _log("🚨 계좌 없음"); return None, ""
        return bc, acc
    except Exception as e:
        _log(f"🚨 브로커 연결 실패: {e}"); return None, ""


def _fills_net(today):
    """★[㉯] 오늘 fills CSV(게이트웨이 체결 직기록) — 종목별 순잔량(매수체결합-매도체결합).
       fill_qty=FID911은 주문별 누적 → (종목,주문번호,방향)별 max 후 합산."""
    fp = FILLS_DIR / f"fills_{today}.csv"
    if not fp.exists():
        return {}
    best = {}
    try:
        with fp.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    if "체결" not in str(r.get("state", "")):
                        continue
                    ot = str(r.get("otype", ""))
                    side = "B" if "매수" in ot else ("S" if "매도" in ot else "")
                    if not side:
                        continue
                    c = str(r.get("code", "")).strip().zfill(6)
                    ono = str(r.get("order_no", "")).strip() or f"?{r.get('ts','')}"
                    q = int(float(r.get("fill_qty") or 0))
                    k = (c, ono, side)
                    if q > best.get(k, 0):
                        best[k] = q
                except Exception:
                    continue
    except Exception:
        return {}
    net = {}
    for (c, _o, side), q in best.items():
        net[c] = net.get(c, 0) + (q if side == "B" else -q)
    return net


def _acct_pass(bc, acc, today):
    """★[㉯ 계좌 대조 2차 패스] 오늘 순잔량>0 인데 실제 계좌에 남아있으면 청산(장부 무관 = 매도 유령 포수).
       매도 수량 = min(오늘 순잔량, 매매가능수량) — 기존 보유·걸린 매도주문은 건드리지 않음."""
    net = {c: n for c, n in _fills_net(today).items() if n > 0}
    # ★[2026-07-19 친구님 승인 — 골짜기 실전전환] 골짜기 사냥꾼(VALLEY·15:10 청산)은 오후까지
    #   보유하는 첫 엔진이라 "아침 매수는 09:43까지 전부 끝난다"는 이 패스의 전제 밖 — 골짜기
    #   장부가 오늘 날짜이고 보유(pos) 또는 체결확인 대기(pending_buy/sell)인 종목만 청산에서
    #   제외한다(골짜기 엔진+전용 FLAT 15:13이 책임). 장부 못 읽으면 기존대로 전부 청산(안전판 우선).
    try:
        VL = json.loads(Path(r"C:\stock_bot\data\valley_hunter_live_ledger.json").read_text(encoding="utf-8-sig"))
        if str(VL.get("date")) == today:
            vheld = {str(c).zfill(6) for c, s in (VL.get("slots", {}) or {}).items()
                     if isinstance(s, dict) and (s.get("pos") or s.get("pending_buy") or s.get("pending_sell"))}
            vdrop = sorted(vheld & set(net))
            if vdrop:
                _log(f"  🏔️골짜기(VALLEY) 관리중 제외: {vdrop} — 골짜기 엔진·전용FLAT(15:13)이 청산 담당")
                for c in vdrop:
                    net.pop(c, None)
    except Exception:
        pass
    # ★[2026-07-22 친구님 승인 — 캡틴2 실전전환] 캡틴2도 종일 보유 엔진(자체 강제청산 15:25) —
    #   골짜기와 동일 원리로, 상태파일이 오늘 날짜이고 보유/주문진행 중인 종목은 이 패스에서
    #   제외한다(캡틴2 엔진이 청산 담당·죽어도 1분 반복 태스크가 재기동-재정박). 못 읽으면 전부 청산.
    try:
        C2 = json.loads(Path(r"C:\stock_bot\data\captain2_state.json").read_text(encoding="utf-8-sig"))
        if str(C2.get("ts", ""))[:10] == f"{today[:4]}-{today[4:6]}-{today[6:8]}":
            c2held = {str(c).zfill(6) for c, s in (C2.get("states", {}) or {}).items()
                      if isinstance(s, dict) and str(s.get("phase")) in
                      ("HOLD", "WATCH", "RECOVERY_HOLD", "BUY_PENDING", "SELL_PENDING")}
            c2drop = sorted(c2held & set(net))
            if c2drop:
                _log(f"  👑2️⃣캡틴2(CAPTAIN2) 관리중 제외: {c2drop} — 캡틴2 엔진(강제청산 15:25)이 담당")
                for c in c2drop:
                    net.pop(c, None)
    except Exception:
        pass
    # ★[2026-07-27 친구님 승인 — 새전략 실전전환] 새전략 S01~S04(공통 회전엔진·최종청산 15:10)도
    #   종일 보유 엔진 — 골짜기·캡틴2와 동일 원리로, 상태파일이 오늘 날짜이고 진행 중
    #   phase(BUY_PENDING/HOLD/SELL_PENDING/RECOVERY_BLOCKED)인 종목은 이 패스에서 제외한다
    #   (각 전략 엔진이 청산·주문복구 담당). 못 읽으면 기존대로 전부 청산(안전판 우선).
    # ★[2026-08-07 보안점검] S06(급락저점추격)이 이 목록에서 빠져 있었다 — 09:43 계좌대조가
    #   S06 보유를 무단 시장가 청산하고 S06 장부엔 HOLD가 남아 유령 잔량이 된다.
    #   ⚠️S06만 positions 키가 "코드:슬롯"(예 010170:1)이라 그냥 넣으면 6자리 코드와 안 맞아
    #     조용히 실패한다 → split(":")[0] 으로 코드만 뽑는다. S01~S05 키는 평코드라 무영향.
    for _sname, _spath in (
            ("S01", r"C:\stock_bot\data\strategy_01_rotation_state_v2.json"),
            ("S02", r"C:\stock_bot\data\strategy_02_rotation_state_v1.json"),
            ("S03", r"C:\stock_bot\data\strategy_03_rotation_state_v1.json"),
            ("S04", r"C:\stock_bot\data\strategy_04_rotation_state_v1.json"),
            ("S05", r"C:\stock_bot\data\strategy_05_rotation_state_v1.json"),
            ("S06", r"C:\stock_bot\data\strategy_06_crash_low_chase_state_v1.json")):
        try:
            ST = json.loads(Path(_spath).read_text(encoding="utf-8-sig"))
            if str(ST.get("date")) != today:
                continue
            sheld = {str(c).split(":")[0].zfill(6) for c, p in (ST.get("positions", {}) or {}).items()
                     if isinstance(p, dict) and str(p.get("phase")) in
                     ("BUY_PENDING", "HOLD", "SELL_PENDING", "RECOVERY_BLOCKED")}
            sdrop = sorted(sheld & set(net))
            if sdrop:
                _log(f"  🧩새전략({_sname}) 관리중 제외: {sdrop} — 전략 엔진이 담당"
                     + ("(밤 넘김 허용·강제청산 없음)" if _sname == "S06" else "(최종청산 15:10)"))
                for c in sdrop:
                    net.pop(c, None)
        except Exception:
            pass
    if not net:
        _log("  🧾계좌대조: 오늘 순잔량 남은 종목 없음 ✓")
        return
    _log(f"  🧾계좌대조: 오늘 순잔량>0 {len(net)}종목 {sorted(net.items())} → 잔고 대조")
    if not LIVE:
        for c, n in sorted(net.items()):
            _log(f"  [그림자] FLATACCT SELL {c} x{n}(순잔량·매매가능 캡 전)")
        return
    if bc is None:
        bc, acc = _connect()
        if bc is None:
            return
    avail = {}
    try:
        r = bc.balance_tr(tr_code="opw00018",
                          inputs={"계좌번호": acc, "비밀번호": "", "비밀번호입력매체구분": "00", "조회구분": "2"},
                          output_fields=["종목번호", "종목명", "보유수량", "매매가능수량"],
                          rqname="FLAT_ACCT_BAL", screen_no="9750", timeout_sec=12.0)
        for x in ((r or {}).get("data") or {}).get("records") or []:
            c = str(x.get("종목번호", "")).strip().lstrip("A").zfill(6)
            try:
                avail[c] = (int(float(str(x.get("매매가능수량") or "0"))), str(x.get("종목명", "")).strip())
            except Exception:
                continue
    except Exception as e:
        _log(f"  🚨 잔고 조회 실패 → 계좌대조 중단: {e}")
        return
    for c, n in sorted(net.items()):
        av, nm = avail.get(c, (0, c))
        sellable = min(n, av)
        if sellable < 1:
            _log(f"  🧾{nm}({c}) 순잔량 {n}·매매가능 {av} → 청산 불필요/불가")
            continue
        try:
            r = bc.send_order_real(
                idempotency_key=f"flatacct_{c}_{uuid.uuid4()}", account=acc,
                code=c, qty=sellable, order_type=2, price=0, hoga_gb="06",
                rqname=f"FLATACCT_SELL_{c}", screen_no="9750")
            st = str((r or {}).get("status", "")).upper()
            _log(f"  🛟🧾 계좌대조 SELL {nm}({c}) x{sellable} (순잔량{n}·매매가능{av}) → {st}"
                 + ("  ★실패-수동확인" if st not in ("OK", "TIMEOUT") else ""))
        except Exception as e:
            _log(f"  🚨 계좌대조 매도 실패 {nm}({c}): {e}")


def main():
    now = datetime.now(); hm = now.strftime("%H%M"); today = now.strftime("%Y%m%d")
    if hm < START or hm > END:
        return
    holds = []
    books = {}   # path → 장부 (매도 성공 시 pos=False 되적기용)
    for path, prefix in LEDGERS:
        try:
            L = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if L.get("date") != today:
            continue
        books[path] = L
        for code, s in (L.get("slots", {}) or {}).items():
            if s.get("pos") and int(s.get("qty", 0) or 0) > 0:
                holds.append((str(code).zfill(6), int(s["qty"]), prefix, s.get("name", code), path))

    _log("=" * 60)
    _log(f"🛟 FLAT 청산 안전판 {'★실전' if LIVE else '그림자(주문0)'} — 장부 보유 {len(holds)}종목")
    bc, acc = None, ""
    sent_any = False
    if not holds:
        _log("  장부 보유 없음 — 엔진이 이미 청산했거나 진입 없음 ✓")
    elif not LIVE:
        for code, qty, pfx, nm, path in holds:
            _log(f"  [그림자] SELL {nm}({code}) x{qty}")
    else:
        bc, acc = _connect()
        if bc is None:
            return
        for code, qty, pfx, nm, path in holds:
            try:
                r = bc.send_order_real(
                    idempotency_key=f"flat_{code}_{uuid.uuid4()}", account=acc,
                    code=code, qty=qty, order_type=2, price=0, hoga_gb="06",
                    rqname=f"{pfx}_SELL_{code}", screen_no="9749")
                st = str((r or {}).get("status", "")).upper()
                sent_any = True
                _log(f"  🛟 FLAT SELL {nm}({code}) x{qty} → {st}"
                     + ("  ★실패-수동확인" if st not in ("OK", "TIMEOUT") else ""))
                if st in ("OK", "TIMEOUT"):
                    # ★[7/16 수술] 판 건 장부에도 되적음 — 뒤에 도는 다른 안전판이 같은 물량을 또 팔지 않게
                    try:
                        s = books[path]["slots"][code]
                        s["pos"] = False; s["qty"] = 0; s["done"] = True
                        p = Path(path); tmp = p.with_suffix(".tmp")
                        tmp.write_text(json.dumps(books[path], ensure_ascii=False, indent=1), encoding="utf-8")
                        os.replace(tmp, p)
                    except Exception as e2:
                        _log(f"  ⚠️ 장부 되적기 실패 {nm}({code}): {e2}")
            except Exception as e:
                _log(f"  🚨 FLAT 매도 실패 {nm}({code}): {e}")

    # ══ ★[7/16 친구님 승인 ㉯] 계좌 대조 2차 패스 — 장부가 뭐라 하든 계좌의 오늘 잔량이 진실 ══
    if ACCT:
        if sent_any:
            time.sleep(4)   # 방금 보낸 장부 패스 매도가 fills CSV에 찍힐 시간(이중매도 방지)
        _acct_pass(bc, acc, today)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"🚨 치명 오류: {e}")
        sys.exit(1)
