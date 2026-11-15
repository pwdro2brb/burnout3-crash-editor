"""Experimental controls retain physical-layout and numeric safeguards.

Synthetic memory uses the actual lane spline and patch generators. No assets,
emulator, sockets, UI or operating-system writes are used by these tests.
"""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import profile
from test_placement import Memory,ribbon,reference


class ExperimentalProfileTests(unittest.TestCase):
    def fixture(self,*,progress=5,lateral=.5):
        memory=Memory()
        ribbon(memory,0,[(i*10,1,0) for i in range(200)])
        row=reference(memory,9,0,progress=progress)
        geometry=profile.lane(memory,0,progress,.5)
        point=[geometry['point'][k]+(lateral-.5)*geometry['lane'][k] for k in range(3)]
        address=profile.VEHICLES+9*profile.VEHICLE_STRIDE
        memory.data.update((address+i,0xA5) for i in range(profile.VEHICLE_STRIDE))
        memory.data.update((row['node']+i,0xA5) for i in range(profile.NODE_STRIDE))
        for offset,dx in ((0,-2),(0x30,2),(0xA0,0)):
            memory.store(address+offset,'<3f',point[0]+dx,point[1],point[2])
        memory.store(row['node']+0x34,'<f',lateral)
        memory.store(row['node']+0x2C,'<f',30)
        memory.store(row['node']+0x41,'<B',0)
        memory.store(profile.MATRICES+9*profile.MATRIX_STRIDE+0x20,'<3f',1,0,0)
        row.update(address=address,kind='independent',type=1,independent=True,
            initialized=True,editable=0 <= lateral <= 1,path_valid=0 <= lateral <= 1,
            position=point,lateral=lateral,node_index=9,parent_id=None,child_id=None)
        return SimpleNamespace(memory=memory,vehicles={9:row},core_paused=True)

    def apply_and_refresh(self,state,patches):
        for patch in patches:
            self.assertEqual(patch.width,4)
            self.assertEqual(state.memory.u32(patch.address),patch.expected)
            state.memory.store(patch.address,'<I',patch.value)
        row=state.vehicles[9]
        row['lateral']=state.memory.read(row['node']+0x34,'<f')[0]
        row['position']=state.memory.xyz(row['address']+0xA0)
        row['path_valid']=row['editable']=0 <= row['lateral'] <= 1

    def test_outside_then_back_changes_only_seven_guarded_float_fields(self):
        state=self.fixture()
        before=dict(state.memory.data)
        row=state.vehicles[9]
        addresses={row['address']+offset+axis*4 for offset in (0,0x30,0xA0) for axis in (0,2)}
        addresses.add(row['node']+0x34)
        outgoing=profile.lateral_patches(state,9,250,experimental=True)
        self.assertEqual({patch.address for patch in outgoing},addresses)
        self.assertEqual(len(outgoing),7)
        self.assertEqual(state.memory.data,before,'Preparing patches must not mutate memory')
        self.apply_and_refresh(state,outgoing)
        self.assertEqual(row['lateral'],2.5)
        self.assertFalse(row['editable'])
        self.assertTrue(profile.can_move_experimental(state.vehicles,row))
        allowed={address+k for address in addresses for k in range(4)}
        self.assertTrue(all(value == state.memory.data[address]
                            for address,value in before.items() if address not in allowed))
        back=profile.lateral_patches(state,9,50,experimental=True)
        self.assertEqual({patch.address for patch in back},addresses)
        self.apply_and_refresh(state,back)
        self.assertEqual(row['lateral'],.5)
        self.assertTrue(row['editable'])
        self.assertTrue(all(value == state.memory.data[address]
                            for address,value in before.items() if address not in allowed))
        for address in addresses:
            original=struct.unpack('<f',bytes(before[address+k] for k in range(4)))[0]
            actual=state.memory.read(address,'<f')[0]
            self.assertAlmostEqual(actual,original,places=6)

    def test_normal_mode_rejects_outside_target_and_cannot_bypass_return_guard(self):
        state=self.fixture()
        with self.assertRaises(profile.ProfileError):
            profile.lateral_patches(state,9,150)
        outside=self.fixture(lateral=-1.5)
        before=dict(outside.memory.data)
        with self.assertRaises(profile.ProfileError):
            profile.lateral_patches(outside,9,50)
        self.assertEqual(outside.memory.data,before)
        self.assertEqual(len(profile.lateral_patches(outside,9,50,experimental=True)),7)

    def test_unknown_incomplete_relinked_or_missing_node_layout_stays_blocked(self):
        cases=[{'type':6},{'initialized':False},{'independent':False,'child_id':14},
               {'node_index':None},{'path':255},{'progress':float('nan')},
               {'lateral':float('inf')},{'progress':-1}]
        for changes in cases:
            with self.subTest(changes=changes):
                state=self.fixture(lateral=2)
                row=state.vehicles[9]
                row.update(changes)
                before=dict(state.memory.data)
                self.assertFalse(profile.can_move_experimental(state.vehicles,row))
                with self.assertRaises(profile.ProfileError):
                    profile.lateral_patches(state,9,50,experimental=True)
                self.assertEqual(state.memory.data,before)

    def test_finite_fraction_outside_float32_raises_profile_error_before_patches(self):
        for target in (1e42,-1e42,1e308):
            with self.subTest(target=target):
                state=self.fixture()
                before=dict(state.memory.data)
                with self.assertRaisesRegex(profile.ProfileError,'float32'):
                    profile.lateral_patches(state,9,target,experimental=True)
                self.assertEqual(state.memory.data,before)

    def test_representable_fraction_with_overflowing_coordinates_is_rejected(self):
        state=self.fixture()
        before=dict(state.memory.data)
        # Fraction1e38 fits float32, but the ten-unit lane delta does not.
        with self.assertRaisesRegex(profile.ProfileError,'Coordenada'):
            profile.lateral_patches(state,9,1e40,experimental=True)
        self.assertEqual(state.memory.data,before)

    def test_experimental_distance_expands_window_and_accepts_sub_two_gap(self):
        state=self.fixture(progress=150)
        row=state.vehicles[9]
        for gap in (1000,.5):
            with self.subTest(gap=gap):
                actual=profile.behind_progress(state.memory,0,150,.5,gap,
                    node=row['node'],experimental=True)
                origin=profile.lane(state.memory,0,150,.5)['point']
                behind=profile.lane(state.memory,0,actual,.5)['point']
                self.assertAlmostEqual(origin[0]-behind[0],gap,places=6)
                self.assertGreaterEqual(actual,0)
                self.assertLess(actual,150)
                with self.assertRaises(profile.ProfileError):
                    profile.behind_progress(state.memory,0,150,.5,gap,node=row['node'])

    def test_path_end_and_invalid_distance_are_retained_in_experiment(self):
        state=self.fixture(progress=150)
        before=dict(state.memory.data)
        for gap in (2000,0,-1,float('inf'),float('nan'),True):
            with self.subTest(gap=gap),self.assertRaises(profile.ProfileError):
                profile.behind_progress(state.memory,0,150,.5,gap,experimental=True)
        self.assertEqual(state.memory.data,before)

    def test_native_direction_and_path_registration_guards_survive_experiment(self):
        for changed in ('speed','path','forward'):
            with self.subTest(changed=changed):
                state=self.fixture(progress=150)
                row=state.vehicles[9]
                if changed=='speed': state.memory.store(row['node']+0x2C,'<f',-1)
                elif changed=='path': state.memory.store(row['node']+0x41,'<B',1)
                else: state.memory.store(profile.MATRICES+9*profile.MATRIX_STRIDE+0x20,'<3f',-1,0,0)
                before=dict(state.memory.data)
                with self.assertRaises(profile.ProfileError):
                    profile.behind_progress(state.memory,0,150,.5,100,node=row['node'],experimental=True)
                self.assertEqual(state.memory.data,before)


if __name__=='__main__':
    unittest.main()
