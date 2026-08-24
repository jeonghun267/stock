# -*- coding: utf-8 -*-
"""[READ-CACHE 잠금 2026-08-05 친구님 지시 "다른 세션들이 끌까봐 걱정이 돼"]

읽기 캐시 배선이 살아 있는지 지킨다. 누가 지우면 이 시험이 빨갛게 터진다.

★왜 이 시험이 있나 — 지우기 전에 반드시 읽을 것
  8/5 실측: 자료(스냅샷)는 초당 1회 오는데 엔진은 2.34초마다 판정했다.
  범인은 전략이 아니라 파일 재읽기였다.
    · 돈맥_1분봉.json 5.56MB 를 한 틱에 5~6번
    · ma3_common_v1.load_payload() 가 payload 없이 불릴 때 종목마다 또 통째로
    · 봉 모자라면 2.58MB 시드까지 종목마다
  그 결과 매도 "3초 확인"이 표본을 1~2개밖에 못 받아 사실상 즉시 매도였다.
  같은 score=4/5 인데 표본 간격 2.6초는 안 팔리고 3.7초는 팔렸다(감사기록 실측).
  캐시를 넣고 한 틱 읽기가 1484ms -> 168ms 가 됐다.

  ⚠️이 배선을 되돌리면 그 병이 그대로 돌아온다. 매도 타점이 다시 스냅샷 운으로 정해진다.
  근거 전문: C:\\stock_bot\\memory.md 8/5 저녁 항목 · data\\audit\\hold_sell\\

정말로 되돌려야 한다면: 이 시험을 지우지 말고 memory.md 에 이유를 먼저 적을 것.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

RUN = Path(r"C:\stock_bot\RUN")
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))


def source(name: str) -> str:
    return (RUN / name).read_text(encoding="utf-8")


class ReadCacheWiringTests(unittest.TestCase):
    """배선이 지워졌는지 원문에서 직접 확인한다(import 만으로는 못 잡는다)."""

    def test_common_module_exists(self):
        self.assertTrue(
            (RUN / "json_cache_v1.py").exists(),
            "json_cache_v1.py 가 사라졌다. 읽기 캐시 공통모듈이다 — 파일 맨 위 설명을 읽을 것.",
        )

    def test_cache_actually_caches(self):
        """mtime+크기가 같으면 같은 객체를 돌려줘야 한다(=파일을 다시 안 읽는다)."""
        import json_cache_v1

        json_cache_v1.clear()
        bars = Path(r"C:\stock_bot\data\돈맥_1분봉.json")
        if not bars.exists():
            self.skipTest("1분봉 파일 없음")
        first = json_cache_v1.read_json_cached(bars, {})
        second = json_cache_v1.read_json_cached(bars, {})
        self.assertIs(
            first, second,
            "같은 파일을 두 번 읽었는데 다른 객체가 나왔다 = 캐시가 죽었다.",
        )

    def test_cache_reloads_when_file_changes(self):
        """캐시가 낡은 자료를 물고 있으면 안 된다."""
        import json_cache_v1

        tmp = Path(r"C:\stock_bot\data\_read_cache_probe.json")
        try:
            tmp.write_text('{"v": 1}', encoding="utf-8")
            self.assertEqual(json_cache_v1.read_json_cached(tmp, {}), {"v": 1})
            tmp.write_text('{"v": 2}', encoding="utf-8")
            self.assertEqual(
                json_cache_v1.read_json_cached(tmp, {}), {"v": 2},
                "파일이 바뀌었는데 옛 자료가 나왔다 = 캐시가 위험하다.",
            )
        finally:
            tmp.unlink(missing_ok=True)

    def test_rotation_core_uses_cache_for_hot_files(self):
        """공용코어(S01~S05)의 1분봉·스냅샷·보드 읽기가 전부 캐시판이어야 한다."""
        text = source("strategy_01_rotation_engine_v2.py")
        # ★assertIn 을 쓰면 실패할 때 파일 전문을 토해내서 못 읽는다. 짧게 낸다.
        self.assertTrue(
            "from json_cache_v1 import read_json_cached" in text,
            "공용코어가 공통 캐시모듈을 import 하지 않는다 "
            "(strategy_01_rotation_engine_v2.py).",
        )
        for field in ("bars_path", "snapshot_path", "board_path"):
            plain = len(re.findall(
                r"read_json\(self\.config\." + field + r", \{\}\)", text))
            cached = text.count(f"read_json_cached(self.config.{field}, {{}})")
            self.assertGreater(
                cached, 0,
                f"공용코어의 {field} 읽기가 캐시판이 아니다 — 한 틱에 여러 번 읽게 된다.",
            )
            self.assertEqual(
                plain, 0,
                f"공용코어에 캐시 안 쓰는 {field} 읽기가 {plain}곳 남아 있다.",
            )

    def test_bars_read_count_is_not_multiplied(self):
        """1분봉을 한 틱에 여러 곳에서 읽는 구조 자체는 그대로다 —
        그래서 캐시가 반드시 붙어 있어야 한다. 읽는 곳이 2곳 이상이면 캐시 필수."""
        text = source("strategy_01_rotation_engine_v2.py")
        hits = text.count("read_json_cached(self.config.bars_path, {})")
        self.assertGreaterEqual(
            hits, 2,
            "1분봉 읽기 지점이 줄었다면 이 시험의 전제를 다시 볼 것.",
        )

    def test_ma3_common_uses_cache(self):
        """ma3_common_v1 은 종목마다 불린다 — 여기서 통째로 읽으면 곱해진다."""
        text = source("ma3_common_v1.py")
        self.assertTrue(
            "from json_cache_v1 import read_json_cached" in text,
            "ma3_common_v1 이 공통 캐시모듈을 import 하지 않는다 "
            "= 종목마다 5.56MB 를 다시 읽게 된다.",
        )
        self.assertTrue(
            'path.read_text(encoding="utf-8-sig")' not in text,
            "ma3_common_v1 이 파일을 직접 다시 읽고 있다 = 종목마다 5.56MB 재읽기.",
        )


if __name__ == "__main__":
    unittest.main()
