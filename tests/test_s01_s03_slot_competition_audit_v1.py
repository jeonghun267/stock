import json,sys,tempfile,unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"RUN"))
import shared_slots as s
class TestAudit(unittest.TestCase):
 def test_first_come_and_audit(self):
  with tempfile.TemporaryDirectory() as raw:
   r=Path(raw); old=(s.FILE,s.AUDIT_DIR,s.REGIME_CACHE_DIR); s.FILE=r/"slots.json"; s.AUDIT_DIR=r/"audit"; s.REGIME_CACHE_DIR=r
   (r/"market_regime_20260825.json").write_text('{"regime":"BEAR"}')
   now=datetime.now().astimezone().isoformat()
   try:
    self.assertTrue(s.acquire_with_audit("000001","STRATEGY01","20260825",buy_ready_ts=now))
    self.assertFalse(s.acquire_with_audit("000001","STRATEGY03","20260825",buy_ready_ts=now))
    rows=[json.loads(x) for x in (r/"audit/s01_s03_slot_competition_20260825.jsonl").read_text().splitlines()]
    self.assertEqual((rows[1]["strategy_id"],rows[1]["acquire_success"],rows[1]["used_slots_before"],rows[1]["peer_fresh_buy_ready"],rows[1]["final_slot_acquired_strategy"],rows[1]["regime"]),("S03",False,1,True,"S01","BEAR"))
   finally: s.FILE,s.AUDIT_DIR,s.REGIME_CACHE_DIR=old
if __name__=="__main__": unittest.main()
