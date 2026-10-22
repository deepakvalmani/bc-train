import unittest
import json,tempfile,zipfile
from pathlib import Path
from train_v43 import MAPS,render,acceptable,completed,reference_ok
class TrainingContracts(unittest.TestCase):
 def test_reference_guard_rejects_regression_faults_and_missing_cases(self):
  rows=[dict(map=m,side=s,opponent=op,won=False,share=.5,faults=0)
        for m in MAPS for s in (0,1) for op in ('v36','v38')]
  for row in rows[:57]:row['won']=True
  self.assertTrue(reference_ok(rows))
  self.assertFalse(reference_ok(rows,58))
  rows[56]['won']=False;self.assertFalse(reference_ok(rows))
  rows[56]['won']=True;rows[0]['faults']=1;self.assertFalse(reference_ok(rows))
  rows[0]['faults']=0;self.assertFalse(reference_ok(rows[:-1]))
  rows[-1]=dict(rows[0]);self.assertFalse(reference_ok(rows))
 def rows(self):return [dict(map=m,side=s,won=s==0,share=.5,faults=0) for m in MAPS for s in (0,1)]
 def test_requires_complete_schedule_and_actual_win_gain(self):
  old=self.rows();new=self.rows();new[1]['won']=True
  self.assertTrue(acceptable(new,old))
  self.assertFalse(acceptable(new[:-1],old))
  self.assertFalse(acceptable(old,old))
  new[0]['faults']=1;self.assertFalse(acceptable(new,old))
 def test_cannot_trade_an_existing_map_win_for_other_maps(self):
  old=self.rows();new=self.rows();new[1]['won']=True;new[3]['won']=True;new[4]['won']=False
  self.assertFalse(acceptable(new,old))
 def test_overlay_preserves_original_dispatch_and_bounds(self):
  base='namespace map_policies { inline Policy for_map(Map id){return accepted();} }'
  new=render(base,{'rushbait-v2':{'bank_k':8.0}})
  self.assertIn('base_for_map(Map id)',new);self.assertIn('Map::rushbait_v2:p.bank_k=8.0;',new)
  with self.assertRaises(ValueError):render(base,{'rows':{'bank_k':999}})
 def test_interrupted_evidence_is_not_reused(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'match.json';path.write_text('{')
   self.assertFalse(completed(path))
   path.write_text(json.dumps({'match':{'outcome':'teamA'},'teams':[{'team':'teamA'},{'team':'teamB'}]}))
   self.assertFalse(completed(path))
   with zipfile.ZipFile(path.with_suffix('.repl26a'),'w') as z:
    z.writestr('team-a.stdout','');z.writestr('team-b.stdout','')
   self.assertTrue(completed(path))
if __name__=='__main__':unittest.main()
