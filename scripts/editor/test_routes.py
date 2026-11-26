"""Read-only route drawing uses real spline formulas and synthetic records."""
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import profile,routes
from test_placement import Memory,ribbon,reference


class RouteNetworkTests(unittest.TestCase):
    def fixture(self):
        memory=Memory()
        ribbon(memory,0,[(i*10,i*.25,0) for i in range(7)],width=10)
        row=reference(memory,9,0)
        return SimpleNamespace(memory=memory,vehicles={9:row},core_paused=True)

    def test_ribbon_contains_both_edges_center_height_and_read_only_metadata(self):
        state=self.fixture()
        state.vehicles[9].update(initialized=False,can_reference=False)
        before=dict(state.memory.data)
        result=routes.build_network(state)
        self.assertEqual([p['id'] for p in result['paths']],[0])
        path=result['paths'][0]
        self.assertEqual(path['vehicle_ids'],[9])
        self.assertFalse(path['traffic_direction_verified'])
        self.assertEqual(path['sample_count'],28)
        for index,middle in enumerate(path['center']):
            progress=6*index/(path['sample_count']-1)
            expected=profile.lane(state.memory,0,progress,.5)['point']
            for actual,wanted in zip(middle,expected): self.assertAlmostEqual(actual,wanted)
        self.assertAlmostEqual(result['bounds']['min'][2],-5)
        self.assertAlmostEqual(result['bounds']['max'][2],5)
        self.assertGreater(result['bounds']['max'][1],result['bounds']['min'][1])
        self.assertEqual(state.memory.data,before)
        self.assertTrue(path['approximate'])
        json.dumps(result,allow_nan=False)

    def test_curved_path_is_sampled_across_full_loaded_progression(self):
        state=self.fixture()
        centers=[(i*8,3+i*.3,(i-3)**2*2) for i in range(8)]
        ribbon(state.memory,1,centers,width=8)
        state.vehicles={4:reference(state.memory,4,1,progress=1.25)}
        result=routes.build_network(state,scan_unreferenced=False)
        path=result['paths'][0]
        for index in (0,len(path['center'])//2,len(path['center'])-1):
            expected=profile.lane(state.memory,1,7*index/(len(path['center'])-1),.5)['point']
            for actual,wanted in zip(path['center'][index],expected): self.assertAlmostEqual(actual,wanted)
        xs=[point[0] for point in path['center']]
        zs=[point[2] for point in path['center']]
        self.assertGreater(max(xs)-min(xs),40)
        self.assertGreater(max(zs)-min(zs),15)

    def test_identity_checked_unreferenced_loaded_path_can_be_shown(self):
        state=self.fixture()
        ribbon(state.memory,2,[(i*10,5,100) for i in range(7)])
        all_paths=routes.build_network(state)
        self.assertEqual([p['id'] for p in all_paths['paths']],[0,2])
        self.assertEqual(all_paths['paths'][1]['vehicle_ids'],[])
        self.assertEqual(all_paths['paths'][1]['source'],'descriptor_candidate')
        self.assertFalse(all_paths['paths'][1]['reference_observed'])
        self.assertEqual(all_paths['unreferenced_path_count'],1)
        self.assertFalse(all_paths['paths'][1]['traffic_direction_verified'])
        referenced=routes.build_network(state,scan_unreferenced=False)
        self.assertEqual([p['id'] for p in referenced['paths']],[0])

    def test_invalid_identity_or_interior_geometry_omits_whole_path_only(self):
        for bad in ('identity','interior','pointer'):
            with self.subTest(bad=bad):
                state=self.fixture()
                ribbon(state.memory,1,[(i*10,5,100) for i in range(7)])
                state.vehicles[2]=reference(state.memory,2,1)
                if bad=='identity': state.memory.store(profile.PATHS+profile.PATH_STRIDE+0x47,'<B',2)
                elif bad=='interior': state.memory.store(0x111000+6*16,'<f',float('nan'))
                else: state.memory.store(profile.PATHS+profile.PATH_STRIDE,'<I',0x1FFFFF8)
                result=routes.build_network(state)
                self.assertEqual([p['id'] for p in result['paths']],[0])
                self.assertIn(1,result['omitted_path_ids'])
                self.assertTrue(result['warning'])

    def test_global_point_budget_preserves_minimum_samples_and_reports_partial_scan(self):
        state=self.fixture()
        ribbon(state.memory,1,[(i*10,5,100) for i in range(7)])
        state.vehicles[2]=reference(state.memory,2,1)
        result=routes.build_network(state,point_budget=4)
        self.assertEqual(result['sample_count'],4)
        self.assertEqual([p['sample_count'] for p in result['paths']],[2,2])
        self.assertTrue(result['truncated'])
        self.assertFalse(result['scan_complete'])
        self.assertLessEqual(result['sample_count'],result['point_budget'])

    def test_read_budget_never_keeps_an_incomplete_polyline(self):
        state=self.fixture()
        ribbon(state.memory,1,[(i*10,5,100) for i in range(7)])
        state.vehicles[2]=reference(state.memory,2,1)
        result=routes.build_network(state,point_budget=4,read_budget=600,scan_unreferenced=False)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(result['read_bytes'],600)
        self.assertEqual(result['paths'],[])
        self.assertTrue(result['omitted_path_ids'])

    def test_cached_memory_preflights_page_fetch_cost_before_reading(self):
        state=self.fixture()
        raw=state.memory.data
        class Client:
            def __init__(self): self.reads=[]
            def read_bytes(self,address,length):
                self.reads.append((address,length))
                return bytes(raw.get(address+i,0) for i in range(length))
        client=Client()
        state.memory=profile.CachedMemory(client)
        result=routes.build_network(state,read_budget=4096,scan_unreferenced=False)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['read_bytes'],4096)
        self.assertEqual(sum(length for _,length in client.reads),4096)
        self.assertEqual(len(client.reads),1)
        result=routes.build_network(state,read_budget=16384,scan_unreferenced=False)
        self.assertEqual(len(result['paths']),1)
        self.assertLessEqual(result['read_bytes'],16384)
        self.assertEqual(result['read_metric'],'additional_cached_bytes')

    def test_optional_flow_read_limit_preserves_a_complete_ribbon(self):
        state=self.fixture()
        state.memory.store(profile.MATRICES+9*profile.MATRIX_STRIDE+0x20,'<3f',1,0,0)
        result=routes.build_network(state,point_budget=2,read_budget=680,scan_unreferenced=False)
        self.assertEqual(len(result['paths']),1)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(result['read_bytes'],680)
        self.assertFalse(result['paths'][0]['traffic_direction_verified'])
        self.assertTrue(result['paths'][0]['direction_verification_limited'])

    def test_arrow_progression_is_not_mislabeled_as_verified_flow(self):
        for forward,speed,expected in ((1,30,True),(-1,30,False),(1,0,False)):
            with self.subTest(forward=forward,speed=speed):
                state=self.fixture()
                row=state.vehicles[9]
                row['travel_speed']=speed
                state.memory.store(profile.MATRICES+9*profile.MATRIX_STRIDE+0x20,'<3f',forward,0,0)
                path=routes.build_network(state,scan_unreferenced=False)['paths'][0]
                self.assertEqual(path['traffic_direction_verified'],expected)
                self.assertTrue(all(a['to'][0]>a['from'][0] for a in path['arrows']))
                self.assertEqual(path['direction_label'],'Path progression')

    def test_reversed_control_points_produce_reversed_arrows(self):
        state=self.fixture()
        ribbon(state.memory,2,[(60-i*10,0,0) for i in range(7)])
        state.vehicles={2:reference(state.memory,2,2)}
        path=routes.build_network(state,scan_unreferenced=False)['paths'][0]
        self.assertTrue(path['arrows'])
        self.assertTrue(all(a['to'][0]<a['from'][0] for a in path['arrows']))
        self.assertGreater(path['center'][0][0],path['center'][-1][0])

    def test_invalid_options_or_running_state_are_rejected_before_reads(self):
        state=self.fixture()
        for options in ({'point_budget':True},{'point_budget':1},{'point_budget':8193},
                        {'read_budget':0},{'read_budget':True},{'scan_unreferenced':1}):
            with self.subTest(options=options),self.assertRaises(profile.ProfileError):
                routes.build_network(state,**options)
        state.core_paused=False
        state.memory=None
        with self.assertRaises(profile.ProfileError): routes.build_network(state)


if __name__=='__main__':
    unittest.main()
