"""Desired traffic speed edits are confined to one proven control float."""
from pathlib import Path
import math
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import profile,speed
from test_placement import Memory


class SpeedTests(unittest.TestCase):
    def fixture(self,*,control=50.,travel=22.352,type_code=1):
        memory=Memory()
        vehicle_id,index=9,3
        address=profile.VEHICLES+vehicle_id*profile.VEHICLE_STRIDE
        node=profile.NODES+index*profile.NODE_STRIDE
        memory.data.update((address+i,0xA5) for i in range(profile.VEHICLE_STRIDE))
        memory.data.update((node+i,0xA5) for i in range(profile.NODE_STRIDE))
        memory.store(address+0x114,'<I',node)
        memory.store(node,'<f',control)
        memory.store(node+0x24,'<f',1.25)
        memory.store(node+0x2C,'<f',travel)
        memory.store(node+0x41,'<B',2)
        memory.store(node+0x46,'<B',1)
        memory.store(node+0x49,'<B',index)
        memory.store(node+0x4A,'<B',vehicle_id)
        row=dict(id=vehicle_id,address=address,node=node,node_index=index,
            path=2,progress=20.,path_valid=True,initialized=True,parent_id=None,
            type=type_code,independent=type_code!=4,kind='truck' if type_code==4 else 'independent',
            native_pair_valid=type_code==4,can_edit_compound=type_code==4,
            speed=memory.read(node,'<f')[0],travel_speed=memory.read(node+0x2C,'<f')[0],
            spacing_scalar=1.25)
        return SimpleNamespace(memory=memory,vehicles={vehicle_id:row},core_paused=True)

    def test_nominal_target_and_current_are_distinct_and_not_physical_measurements(self):
        row=self.fixture(control=50,travel=0).vehicles[9]
        info=speed.summarize(row)
        self.assertAlmostEqual(info['nominal_target_kmh'],80.4672)
        self.assertEqual(info['nominal_travel_kmh'],0)
        self.assertEqual(info['control_value'],50)
        self.assertEqual(info['travel_value'],0)
        self.assertTrue(info['stopped'])
        self.assertFalse(info['physical_speed_measured'])
        self.assertEqual(info['conversion'],'nominal')
        self.assertTrue(info['can_set_speed'],'Stopping must not prevent later increasing the desired speed')

    def test_each_supported_layout_changes_only_one_control_float(self):
        for type_code in (1,2,3,4,5):
            with self.subTest(type_code=type_code):
                state=self.fixture(type_code=type_code)
                before=dict(state.memory.data)
                row=state.vehicles[9]
                patches=speed.patches(state,9,30)
                self.assertEqual(state.memory.data,before)
                self.assertEqual(len(patches),1)
                patch=patches[0]
                self.assertEqual((patch.address,patch.width),(row['node'],4))
                self.assertEqual(patch.expected,state.memory.u32(row['node']))
                state.memory.store(patch.address,'<I',patch.value)
                self.assertEqual(state.memory.read(row['node'],'<f')[0],30)
                allowed=set(range(row['node'],row['node']+4))
                self.assertTrue(all(state.memory.data[a]==v for a,v in before.items() if a not in allowed))
                self.assertEqual(state.memory.read(row['node']+0x24,'<f')[0],1.25)
                self.assertEqual(state.memory.read(row['node']+0x2C,'<f')[0],row['travel_speed'])

    def test_zero_target_can_be_stopped_and_later_increased_without_current_speed_write(self):
        state=self.fixture(control=0,travel=0)
        self.assertTrue(speed.can_set_speed(state.vehicles[9]))
        self.assertEqual(struct.unpack('<f',speed.patches(state,9,40)[0].value.to_bytes(4,'little'))[0],40)
        state=self.fixture()
        self.assertEqual(speed.patches(state,9,0)[0].value,0)

    def test_nonready_child_and_unknown_layouts_remain_blocked(self):
        cases=[dict(initialized=False),dict(path_valid=False),dict(parent_id=4),dict(type=11),
               dict(type=7),dict(node_index=None),dict(path=255),dict(progress=float('nan')),
               dict(independent=False),dict(address=0x1234),dict(type=4,kind='truck',native_pair_valid=False)]
        for changes in cases:
            with self.subTest(changes=changes):
                state=self.fixture()
                state.vehicles[9].update(changes)
                self.assertFalse(speed.can_set_speed(state.vehicles[9]))
                with self.assertRaises(profile.ProfileError):speed.patches(state,9,20)

    def test_node_identity_and_liveness_are_rechecked_before_preparing_patch(self):
        for offset,value in ((0x49,10),(0x4A,10),(0x41,3),(0x46,0),(0x46,255)):
            with self.subTest(offset=offset,value=value):
                state=self.fixture();row=state.vehicles[9]
                state.memory.store(row['node']+offset,'<B',value)
                with self.assertRaisesRegex(profile.ProfileError,'nó'):
                    speed.patches(state,9,20)
        state=self.fixture();row=state.vehicles[9]
        state.memory.store(row['address']+0x114,'<I',row['node']+profile.NODE_STRIDE)
        with self.assertRaises(profile.ProfileError):speed.patches(state,9,20)

    def test_normal_bounds_experimental_float32_and_pause_guard(self):
        state=self.fixture()
        for value in (-1,241,True,float('nan'),float('inf'),'20'):
            with self.subTest(value=value),self.assertRaises(profile.ProfileError):
                speed.patches(state,9,value)
        self.assertEqual(len(speed.patches(state,9,1000,experimental=True)),1)
        for value in (-1,1e308,float('nan')):
            with self.subTest(value=value),self.assertRaises(profile.ProfileError):
                speed.patches(state,9,value,experimental=True)
        with self.assertRaises(profile.ProfileError):speed.patches(state,9,30,experimental=1)
        state.core_paused=False
        with self.assertRaises(profile.ProfileError):speed.patches(state,9,30)

    def test_unknown_current_control_is_not_overwritten(self):
        state=self.fixture();row=state.vehicles[9]
        state.memory.store(row['node'],'<f',35)
        with self.assertRaisesRegex(profile.ProfileError,'mudou'):
            speed.patches(state,9,20)
        for name,value in (('speed',float('nan')),('travel_speed',float('inf')),('spacing_scalar',float('nan'))):
            state=self.fixture();state.vehicles[9][name]=value
            info=speed.summarize(state.vehicles[9])
            self.assertFalse(info['can_set_speed'])
            self.assertIsNone(info[{'speed':'control_value','travel_speed':'travel_value','spacing_scalar':'spacing_value'}[name]])

    def test_missing_node_and_child_defaults_are_unknown_instead_of_real_zero_speed(self):
        for child in (False,True):
            with self.subTest(child=child):
                row=self.fixture().vehicles[9]
                row.update(node=0,node_index=None,speed=0.,travel_speed=0.,spacing_scalar=0.,
                           parent_id=4 if child else None)
                info=speed.summarize(row)
                for field in ('control_value','travel_value','spacing_value','nominal_target_kmh','nominal_travel_kmh','stopped'):
                    self.assertIsNone(info[field])
                self.assertFalse(info['can_set_speed'])
                self.assertIn('cabine' if child else 'indisponível',info['note'])

    def test_enormous_integer_is_friendly_invalid_input_not_an_overflow_exception(self):
        state=self.fixture()
        huge=10**1000
        with self.assertRaises(profile.ProfileError):speed.patches(state,9,huge,experimental=True)
        state.vehicles[9]['speed']=huge
        self.assertIsNone(speed.summarize(state.vehicles[9])['control_value'])

    def test_pure_recipe_validator_rounds_to_finite_float32_without_a_snapshot(self):
        expected=struct.unpack('<f',struct.pack('<f',30.1))[0]
        self.assertEqual(speed.validate_control(30.1),expected)
        self.assertEqual(speed.validate_control(0),0)
        self.assertEqual(speed.validate_control(1000,experimental=True),1000)
        for value in (1e308,-1,True,float('nan'),10**1000):
            with self.subTest(value=value),self.assertRaises(profile.ProfileError):
                speed.validate_control(value,experimental=True)


if __name__=='__main__':unittest.main()
