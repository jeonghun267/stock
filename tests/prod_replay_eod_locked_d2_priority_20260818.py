import importlib.util
import json
import tempfile
from pathlib import Path


PROD = Path(r"C:\stock_bot\RUN\eod_gap_live_executor_v1.py")


def load_prod():
    spec = importlib.util.spec_from_file_location("eod_gap_live_executor_v1", PROD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def isolate_outputs(mod, root):
    root.mkdir(parents=True, exist_ok=True)
    mod.LIVE = False
    mod.POS = root / "positions.json"
    mod.POS.write_text("{}", encoding="utf-8")
    mod.LOG = root / "replay.log"
    mod.SUP_DIR = root / "supply"
    mod.LEAD_SHADOW = root / "leader.csv"
    mod.MICRO_WATCH_FILE = root / "micro_watch.json"
    mod.AUCTION_AUDIT_DIR = root / "auction"
    mod._pick_window_open = lambda: True


def run():
    with tempfile.TemporaryDirectory(prefix="eodgap_locked_d2_") as td:
        root = Path(td)
        fixture = root / "broker_inputs.json"

        capture = load_prod()
        isolate_outputs(capture, root / "capture")
        real_top = capture._opt10032_top
        real_extra = capture._limitup_extra
        saved = {}
        picked_capture = []

        def capture_top(bc, n):
            rows = real_top(bc, n)
            saved["top"] = rows
            return rows

        def capture_extra(bc, exclude, min_chg=28.0, max_add=10):
            rows = real_extra(bc, exclude, min_chg=min_chg, max_add=max_add)
            saved["extra"] = rows
            return rows

        capture._opt10032_top = capture_top
        capture._limitup_extra = capture_extra
        capture._buy_one = lambda bc, pick, today, held: picked_capture.append(pick) or True
        capture.mode_pick()
        fixture.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
        if not saved.get("top"):
            # 장 마감 후 opt10032가 빈 응답이면 오늘 실전 로그에 보존된 LOCKED top5로
            # 생산 정렬 함수만 검증한다. 이것은 전체 생산 재생으로 승격하지 않는다.
            actual_locked = [
                (58.3, "098120", "마이크로컨텍솔", 412.0),
                (27.7, "351870", "차이커뮤니케이션", 5.0),
                (27.1, "079190", "케스피온", 27.0),
                (26.8, "019010", "베뉴지", 295.0),
                (25.3, "047770", "코데즈컴바인", 33.0),
            ]
            ranked, d2 = capture._rank_locked_by_d2(actual_locked, "20260818")
            keys = [
                (float(d2.get(c[1], 0) or 0), float(c[0]), float(c[3]))
                for c in ranked
            ]
            if keys != sorted(keys, reverse=True):
                raise AssertionError("D-2 -> score -> value ordering failed")
            print(
                "[UNVERIFIED] FOCUSED_FUNCTION PASS "
                f"code={ranked[0][1]} d2={keys[0][0]:.0f}; "
                "opt10032 unavailable, not PROD_REPLAY"
            )
            return

        replay = load_prod()
        isolate_outputs(replay, root / "replay")
        frozen = json.loads(fixture.read_text(encoding="utf-8"))
        picked_replay = []
        replay._broker = lambda: object()
        replay._opt10032_top = lambda _bc, _n: frozen["top"]
        replay._limitup_extra = lambda _bc, _exclude, min_chg=28.0, max_add=10: frozen.get("extra", [])
        replay._supply_net = lambda _bc, _code: (None, None)
        replay._buy_one = lambda bc, pick, today, held: picked_replay.append(pick) or True
        replay.mode_pick()

        if not picked_capture or not picked_replay:
            raise AssertionError("production pick path produced no candidate")
        if picked_capture[0][1] != picked_replay[0][1]:
            raise AssertionError(
                f"capture/replay mismatch: {picked_capture[0][1]} != {picked_replay[0][1]}"
            )
        log = (root / "replay" / "replay.log").read_text(encoding="utf-8-sig")
        if "[LOCKED-D2]" not in log:
            raise AssertionError("LOCKED-D2 production branch was not executed")
        print(
            "[PROD_REPLAY] PASS "
            f"code={picked_replay[0][1]} score={picked_replay[0][0]} "
            f"fixture_top={len(frozen['top'])} fixture_extra={len(frozen.get('extra', []))}"
        )


if __name__ == "__main__":
    run()
