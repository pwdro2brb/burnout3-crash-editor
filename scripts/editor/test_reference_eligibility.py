"""Stopped and opposite-facing native traffic use their own loaded path."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import profile,placement
import test_experimental_profile as physical_fixtures
import test_placement as geometry_fixtures


class ReferenceEligibilityTests(unittest.TestCase):
    def fixture(self,*,travel=0.,opposite=False):
        state=physical_fixtures.ExperimentalProfileTests().fixture(progress=5)
        row=state.vehicles[9]
        if opposite:
            geometry_fixtures.ribbon(state.memory,0,[(100-i*10,1,0) for i in range(20)])
            state.memory.store(profile.MATRICES+9*profile.MATRIX_STRIDE+0x20,'<3f',-1,0,0)
        state.memory.store(row['node'],'<f',30)
        state.memory.store(row['node']+0x2C,'<f',travel)
        row.update(model_id='TEST_CAR',speed=30.,travel_speed=travel,spacing_scalar=1.5,
                   position=profile.lane(state.memory,0,5,.5)['point'])
        model=dict(id='TEST_CAR',label='Carro de teste',type_label='Carro',verified=True,
            kind='independent',observed_types={1},independent_observed_types={1},
            trailer_model_ids=set(),truck_model_ids=set(),eligible_as_trailer=False,native_pair_valid=False)
        state.models={'TEST_CAR':model}
        profile._compound_metadata(state.vehicles,state.models)
        return profile.Snapshot(state.memory,{},state.vehicles,state.models,True,
                                player=dict(position=[0.,1.,0.],forward=[1.,0.,0.]))

    def test_stopped_reference_can_place_behind_and_at_a_point_without_writes(self):
        state=self.fixture()
        row=state.vehicles[9]
        before=dict(state.memory.data)
        self.assertTrue(row['editable'])
        self.assertTrue(row['can_reference'])
        result=profile.behind_progress(state.memory,0,row['progress'],.5,10,node=row['node'])
        self.assertLess(result,row['progress'])
        projected=placement.project_target(state,9,20,0)
        self.assertEqual(projected['reference_id'],9)
        self.assertEqual(state.memory.data,before)
        public=state.public()['vehicles'][0]
        self.assertTrue(public['can_add'])
        self.assertIsNone(public['reference_reason'])

    def test_opposite_world_direction_is_accepted_when_its_own_spline_agrees(self):
        for travel in (0.,10.):
            with self.subTest(travel=travel):
                state=self.fixture(travel=travel,opposite=True)
                row=state.vehicles[9]
                self.assertTrue(row['can_reference'])
                behind=profile.behind_progress(state.memory,0,5,.5,10,node=row['node'])
                before=profile.lane(state.memory,0,5,.5)['point']
                after=profile.lane(state.memory,0,behind,.5)['point']
                self.assertGreater(after[0],before[0])
                self.assertAlmostEqual(after[0]-before[0],10,places=5)
                self.assertTrue(state.public()['vehicles'][0]['editable'])

    def test_negative_nonfinite_or_outside_constructor_parameters_cannot_reference(self):
        for changes in (dict(travel_speed=-1),dict(travel_speed=float('nan')),
                        dict(speed=-1),dict(speed=241),dict(spacing_scalar=-1),
                        dict(spacing_scalar=float('inf'))):
            with self.subTest(changes=changes):
                state=self.fixture()
                row=state.vehicles[9]
                row.update(changes)
                # Reconstruct observation sets, as snapshot creates new models.
                model=state.models['TEST_CAR']
                model.update(observed_types={1},independent_observed_types={1},
                             trailer_model_ids=set(),truck_model_ids=set())
                profile._compound_metadata(state.vehicles,state.models)
                self.assertFalse(row['can_reference'])
                public=state.public()['vehicles'][0]
                self.assertIsNone(public['edit_reason'])
                self.assertIn('native speed or spacing parameters',public['reference_reason'])

    def test_zero_speed_does_not_bypass_unknown_direction_or_path_owner(self):
        for mutation in ('path','forward'):
            with self.subTest(mutation=mutation):
                state=self.fixture()
                row=state.vehicles[9]
                if mutation=='path': state.memory.store(row['node']+0x41,'<B',2)
                else: state.memory.store(profile.MATRICES+9*profile.MATRIX_STRIDE+0x20,'<3f',-1,0,0)
                before=dict(state.memory.data)
                with self.assertRaises(profile.ProfileError):
                    profile.behind_progress(state.memory,0,5,.5,10,node=row['node'])
                self.assertEqual(state.memory.data,before)

    def test_public_reasons_distinguish_cold_missing_node_and_missing_path(self):
        for changes,expected in ((dict(initialized=False),'physics points'),
                                 (dict(node_index=None),'traffic node'),
                                 (dict(path=255),'traffic path')):
            with self.subTest(changes=changes):
                state=self.fixture()
                row=state.vehicles[9]
                row.update(changes,editable=False,can_reference=False)
                public=state.public()['vehicles'][0]
                self.assertFalse(public['can_reference'])
                self.assertIn(expected,public['edit_reason'])
                self.assertEqual(public['reference_reason'],public['edit_reason'])


if __name__=='__main__':
    unittest.main()
