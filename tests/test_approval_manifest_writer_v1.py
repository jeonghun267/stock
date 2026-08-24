from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


RUN = Path(__file__).resolve().parents[1] / "RUN"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from approval_manifest_writer_v1 import (  # noqa: E402
    ManifestConflict,
    content_sha,
    live_feature_enabled,
    read_content_sha,
    stamp_current_sha,
    update_manifest,
    verify_manifest_sha,
)
from live_owner_approval_guard_v1 import verify_live_hashes  # noqa: E402

ROOT = Path(r"C:\stock_bot")
REAL_MANIFEST = ROOT / "config" / "live_approved_hashes_v1.json"


class ApprovalManifestWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        # ★[2026-08-12 P2-b] repo tests/ 하위에 mkdir 하면 관리자·읽기전용 실행에서
        #   PermissionError 로 테스트가 안 돌 수 있다. OS 임시 폴더로 옮긴다.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "live_approved_hashes_v1.json"
        shutil.copy2(REAL_MANIFEST, self.path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_cas_rejects_stale_edit(self) -> None:
        # A 와 B 가 같은 시점을 읽는다.
        base = read_content_sha(self.path)
        # A 가 먼저 성공적으로 편집한다.
        update_manifest(
            lambda d: {**d, "approval_scope": "edit A"},
            updated_by="A", expect_sha=base, path=self.path, backup=False,
        )
        # B 는 옛 sha 로 편집을 시도한다 -> lost update 를 막아야 한다.
        with self.assertRaises(ManifestConflict):
            update_manifest(
                lambda d: {**d, "approval_scope": "edit B"},
                updated_by="B", expect_sha=base, path=self.path, backup=False,
            )
        # 파일에는 A 의 편집만 남아 있어야 한다.
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self.assertEqual(data["approval_scope"], "edit A")

    def test_missing_expect_sha_is_rejected_without_explicit_bypass(self) -> None:
        # ★[P1-b] CAS 없이 부르면 거부돼야 한다(실수 방지).
        with self.assertRaises(ManifestConflict):
            update_manifest(
                lambda d: {**d, "approval_scope": "no-cas edit"},
                updated_by="tester", expect_sha=None,
                path=self.path, backup=False,
            )
        # 명시적 우회(allow_no_cas=True)만 통과하고 지문은 갱신된다.
        new_sha = update_manifest(
            lambda d: {**d, "approval_scope": "explicit bypass"},
            updated_by="tester", expect_sha=None, allow_no_cas=True,
            path=self.path, backup=False,
        )
        ok, stored, computed = verify_manifest_sha(self.path)
        self.assertTrue(ok)
        self.assertEqual(stored, computed)
        self.assertEqual(stored, new_sha)

    def test_meta_fields_excluded_from_fingerprint(self) -> None:
        update_manifest(
            lambda d: d, updated_by="one",
            expect_sha=read_content_sha(self.path), path=self.path, backup=False)
        sha1 = read_content_sha(self.path)
        # 같은 내용을 다른 사람이 다시 저장해도 지문은 같아야 한다.
        update_manifest(
            lambda d: d, updated_by="two",
            expect_sha=read_content_sha(self.path), path=self.path, backup=False)
        sha2 = read_content_sha(self.path)
        self.assertEqual(sha1, sha2)

    def test_hash_entries_survive_and_guard_still_passes(self) -> None:
        # 지문만 심어도(승인 내용 무변경) 관문이 실제 파일 해시로 여전히 PASS 여야 한다.
        stamp_current_sha(updated_by="stamp-test", path=self.path)
        for strategy in ("S01", "S02", "S03", "S06"):
            passed, errors = verify_live_hashes(
                strategy, root=ROOT, manifest_path=self.path)
            self.assertTrue(passed, f"{strategy}: {errors}")

    def test_live_feature_requires_grant_and_intact_fingerprint(self) -> None:
        # 승인 필드가 없으면 False. (픽스처는 실제 명부 복사본이라 먼저 승인을 비운다.)
        update_manifest(
            lambda d: {**d, "live_features": {}},
            updated_by="baseline", expect_sha=read_content_sha(self.path),
            path=self.path, backup=False,
        )
        self.assertFalse(live_feature_enabled("S03_EARLY_LOW", path=self.path))
        # writer 로 승인하면 True.
        update_manifest(
            lambda d: {**d, "live_features": {"S03_EARLY_LOW": True}},
            updated_by="grant", expect_sha=read_content_sha(self.path),
            path=self.path, backup=False,
        )
        self.assertTrue(live_feature_enabled("S03_EARLY_LOW", path=self.path))
        # 명부를 직접 변조(지문 안 맞음)하면 승인 필드가 True 여도 False 여야 한다.
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        data["live_features"] = {"S03_EARLY_LOW": True, "SNEAKY": True}
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertFalse(live_feature_enabled("S03_EARLY_LOW", path=self.path))

    def test_fingerprint_detects_out_of_band_edit(self) -> None:
        stamp_current_sha(updated_by="baseline", path=self.path)
        # writer 를 우회한 직접 편집을 흉내낸다.
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        data["approval_scope"] = "tampered out of band"
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, _stored, _computed = verify_manifest_sha(self.path)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
