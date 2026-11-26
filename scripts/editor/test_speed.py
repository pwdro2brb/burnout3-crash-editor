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
    def fixture(self,*,control=50.,travel=22.352,type_code=1,vehicle_id=9,index=3):
        memory=Memory()
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

    def multiple_fixture(self):
        states=[self.fixture(vehicle_id=9+i,index=3+i,type_code=kind)
                for i,kind in enumerate((1,5,4))]
        state=states[0]
        for other in states[1:]:
            state.memory.data.update(other.memory.data)
            state.vehicles.update(other.vehicles)
        return state

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
                with self.assertRaisesRegex(profile.ProfileError,'node'):
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
        with self.assertRaisesRegex(profile.ProfileError,'changed'):
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
                self.assertIn('cab' if child else 'unavailable',info['note'])

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

    def test_bulk_prepares_distinct_controls_and_preserves_all_other_bytes(self):
        for selected in ([9,10],[9,10,11]):
            with self.subTest(selected=selected):
                state=self.multiple_fixture()
                before=dict(state.memory.data)
                patches=speed.patches_many(state,selected,30.1)
                self.assertEqual(state.memory.data,before)
                self.assertEqual([p.address for p in patches],[state.vehicles[i]['node'] for i in selected])
                allowed={p.address+k for p in patches for k in range(4)}
                for patch in patches:
                    self.assertEqual(patch.width,4)
                    self.assertEqual(patch.expected,state.memory.u32(patch.address))
                    state.memory.store(patch.address,'<I',patch.value)
                self.assertTrue(all(state.memory.data[a]==v for a,v in before.items() if a not in allowed))
                for index in selected:
                    node=state.vehicles[index]['node']
                    self.assertEqual(state.memory.read(node,'<f')[0],speed.validate_control(30.1))
                    self.assertEqual(state.memory.read(node+0x24,'<f')[0],1.25)
                    self.assertEqual(state.memory.read(node+0x2C,'<f')[0],state.vehicles[index]['travel_speed'])

    def test_bulk_invalid_last_selection_never_changes_an_earlier_target(self):
        for changed in ('not_ready','owner','current_control','child'):
            with self.subTest(changed=changed):
                state=self.multiple_fixture()
                last=state.vehicles[11]
                if changed=='not_ready':last['initialized']=False
                elif changed=='owner':state.memory.store(last['node']+0x4A,'<B',12)
                elif changed=='current_control':state.memory.store(last['node'],'<f',35)
                else:last['parent_id']=10
                before=dict(state.memory.data)
                with self.assertRaises(profile.ProfileError):
                    speed.patches_many(state,[9,10,11],20)
                self.assertEqual(state.memory.data,before)
                self.assertEqual(state.memory.read(state.vehicles[9]['node'],'<f')[0],50)

    def test_bulk_selection_rejects_empty_invalid_duplicate_and_shared_nodes(self):
        for selection in ([],(),[9,9],[True],[9,True],[-1],[254],[999],9,'9',{9},iter([9]),[9]*255):
            with self.subTest(selection=type(selection).__name__):
                state=self.multiple_fixture()
                before=dict(state.memory.data)
                with self.assertRaises(profile.ProfileError):
                    speed.patches_many(state,selection,20)
                self.assertEqual(state.memory.data,before)
        state=self.multiple_fixture()
        state.vehicles[10].update(node=state.vehicles[9]['node'],node_index=state.vehicles[9]['node_index'])
        before=dict(state.memory.data)
        with self.assertRaisesRegex(profile.ProfileError,'same traffic node'):
            speed.patches_many(state,[9,10],20)
        self.assertEqual(state.memory.data,before)

    def test_bulk_zero_experimental_limits_and_pause_guards_are_shared(self):
        state=self.multiple_fixture()
        self.assertTrue(all(p.value==0 for p in speed.patches_many(state,(9,10,11),0)))
        expected=struct.unpack('<I',struct.pack('<f',1000))[0]
        self.assertTrue(all(p.value==expected for p in speed.patches_many(state,[9,10,11],1000,experimental=True)))
        for value,experimental in ((241,False),(-1,True),(float('nan'),True),(1e308,True),(True,False)):
            with self.subTest(value=value),self.assertRaises(profile.ProfileError):
                speed.patches_many(state,[9,10,11],value,experimental=experimental)
        with self.assertRaises(profile.ProfileError):
            speed.patches_many(state,[9,10],20,experimental=1)
        state.core_paused=False
        with self.assertRaises(profile.ProfileError):
            speed.patches_many(state,[9,10],20)

    def test_bulk_single_is_identical_and_snapshot_keys_cannot_alias_another_actor(self):
        state=self.fixture()
        self.assertEqual(speed.patches_many(state,[9],30),speed.patches(state,9,30))
        other=self.fixture(vehicle_id=10,index=4)
        state.memory.data.update(other.memory.data)
        state.vehicles[9]=other.vehicles[10]
        with self.assertRaises(profile.ProfileError):speed.patches_many(state,[9],30)
        with self.assertRaises(profile.ProfileError):speed.patches(state,9,30)


if __name__=='__main__':unittest.main()
