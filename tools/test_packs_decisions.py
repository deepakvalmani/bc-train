import unittest
from packs_decisions import summarize_inspection


class DecisionReportTests(unittest.TestCase):
    def test_delivery_and_death_are_distinguished(self):
        def champion(gems, alive=True):
            return dict(id=0, team=0, type=3, alive=alive, position=dict(x=2,y=2), gems=gems)
        data = dict(rounds=[dict(round=i, champions=[c]) for i,c in enumerate([
            champion(20), champion(20), champion(0), champion(0,False)])],
            acquisitions=[dict(id=0,team=0,round=0,amount=20)],
            deliveries=[], purchases=[],
            drops=[dict(id=0,amount=20,scoreGain=0)],
            deaths=[dict(id=0,carried=0)], events=[], clears=[], terminal={})
        c = summarize_inspection(data,0)['champions'][0]
        self.assertEqual(c['delivered'],0)
        self.assertEqual(c['unsubmitted_bag_decreases'],20)
        self.assertEqual(c['deaths'],1)
        self.assertEqual(c['longest_stationary_carry'],2)
        self.assertIsNone(c['first_delivery'])

    def test_reports_only_selected_team_and_preserves_missing_events(self):
        data=dict(rounds=[dict(round=0,champions=[dict(id=3,team=1,type=11,
                  alive=True,position=dict(x=30,y=30),gems=0)])], acquisitions=[],
                  deliveries=[],purchases=[],drops=[],deaths=[],events=[],clears=[],terminal={})
        self.assertEqual(summarize_inspection(data,0)['champions'],[])
        c=summarize_inspection(data,1)['champions'][0]
        self.assertEqual(c['champion'],'Tavi')
        self.assertIsNone(c['first_move'])
        self.assertIsNone(c['first_acquisition'])


if __name__ == '__main__':
    unittest.main()
