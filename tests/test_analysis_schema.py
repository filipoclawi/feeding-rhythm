import copy, sys, pathlib, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from validate_public import validate_public
from test_schema import fixture

class AnalysisSchemaTests(unittest.TestCase):
 def value(self):
  v=fixture();v['version']=2;v['analysis']=dict(windowStart='2025-12-20',windowEnd='2026-01-02',gaps=[dict(startedAt='2026-01-02T10:00:00Z',gapMinutes=None,status='unknown')],sideDays=[dict(date='2026-01-02',leftMinutes=10,rightMinutes=0,complete=False)])
  return v
 def test_valid(self):validate_public(self.value())
 def test_privacy_and_window(self):
  for path in [('analysis',),('analysis','gaps',0),('analysis','sideDays',0)]:
   v=self.value();target=v
   for k in path:target=target[k]
   target['notes']='PRIVATE_SENTINEL'
   with self.assertRaises(ValueError):validate_public(v)
  for key,value in [('startedAt','2025-12-19T10:00:00Z'),('gapMinutes',10),('status','private')]:
   v=self.value();v['analysis']['gaps'][0][key]=value
   with self.assertRaises(ValueError):validate_public(v)
if __name__=='__main__':unittest.main()
