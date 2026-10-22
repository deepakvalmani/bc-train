import copy
from pathlib import Path
import tempfile
import unittest
import economy_learning as economy
import train


class EconomyTests(unittest.TestCase):
    def test_all_economic_groups_are_explored_and_bounded(self):
        original={**{name:False for name in economy.GROUPS},**economy.DEFAULTS}
        seen=set()
        for cycle in range(120):
            for proposal in economy.proposals(original,cycle):
                seen.update(name for name in economy.DEFAULTS if proposal[name]!=original[name])
                text=economy.header(proposal)
                with tempfile.TemporaryDirectory() as folder:
                    path=Path(folder)/'weights.h'; path.write_text(text)
                    self.assertEqual(economy.read(path),proposal)
        self.assertEqual(seen,set(economy.DEFAULTS))
        self.assertFalse(any(original[name] for name in economy.GROUPS))

    def test_nonfinite_and_missing_settings_are_rejected(self):
        values={**{name:False for name in economy.GROUPS},**economy.DEFAULTS}
        for value in (float('nan'),0,5):
            candidate=dict(values,BANK_RISK_W=value)
            with self.assertRaises(ValueError): economy.header(candidate)

    def test_observed_delivery_delay_and_purchase_accounting(self):
        frames={0:[dict(round=1,gems=0,alive=1,action='walk_camp',banked=0),
                   dict(round=2,gems=20,alive=1,action='tribute_start',banked=0),
                   dict(round=3,gems=20,alive=1,action='tributing',banked=0),
                   dict(round=4,gems=0,alive=1,action='walk_camp',banked=20)]}
        diagnosis=dict(malformed=0)
        text='PX 2 0 1 1 20 30 100 100 1000 0 0 0 0\n'
        economy.enrich(text,frames,diagnosis)
        self.assertEqual(diagnosis['observed_gems_acquired'],20)
        self.assertEqual(diagnosis['inferred_personal_gems_tributed'],20)
        self.assertEqual(diagnosis['mean_observed_delivery_delay'],2)
        self.assertEqual(diagnosis['observed_shop_spend'],30)

    def test_gap_does_not_invent_delivery_age(self):
        frames={0:[dict(round=1,gems=20,alive=1,action='tributing',banked=0),
                   dict(round=4,gems=0,alive=1,action='walk_camp',banked=20)]}
        diagnosis=dict(malformed=0)
        economy.enrich('',frames,diagnosis)
        self.assertIsNone(diagnosis['mean_observed_delivery_delay'])


if __name__=='__main__': unittest.main()
