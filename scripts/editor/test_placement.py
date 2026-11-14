"""Projection against real spline formulas and synthetic loaded path records."""
from pathlib import Path
import math
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import placement,profile


class Memory:
    def __init__(self): self.data={}
    def store(self,address,format_,*values):
        self.data.update((address+i,b) for i,b in enumerate(struct.pack(format_,*values)))
    def read(self,address,format_):
        return struct.unpack(format_,bytes(self.data[address+i] for i in range(struct.calcsize(format_))))
    def xyz(self,address): return list(self.read(address,'<3f'))
    def u8(self,address): return self.read(address,'<B')[0]
    def u32(self,address): return self.read(address,'<I')[0]


def ribbon(memory,path,points,width=10):
    descriptor=profile.PATHS+path*profile.PATH_STRIDE
    geometry=0x100000+path*0x10000
    pairs,vertices=geometry+0x100,geometry+0x1000
    memory.store(descriptor,'<I',geometry)
    memory.store(descriptor+0x47,'<B',path)
    memory.store(geometry,'<I',pairs)
    memory.store(geometry+0xC,'<II',vertices,len(points))
    for index,center in enumerate(points):
        previous,following=points[max(0,index-1)],points[min(len(points)-1,index+1)]
        dx,dz=following[0]-previous[0],following[2]-previous[2]
        length=math.hypot(dx,dz)
        normal=(-dz/length,0,dx/length)
        memory.store(pairs+index*4,'<2H',2*index,2*index+1)
        for side,sign in ((0,-1),(1,1)):
            memory.store(vertices+(2*index+side)*16,'<4f',
                *(center[k]+sign*normal[k]*width/2 for k in range(3)),0)


def reference(memory,index,path,progress=2,lateral=.5,residual=(0,0,0)):
    point=profile.lane(memory,path,progress,lateral)['point']
    return dict(id=index,path=path,progress=progress,lateral=lateral,
        position=[point[k]+residual[k] for k in range(3)],initialized=True,
        path_valid=True,can_reference=True,node=0x551910+index*0x50,
        speed=30,travel_speed=30,spacing_scalar=1.5)


class PlacementTests(unittest.TestCase):
    def fixture(self):
        memory=Memory()
        ribbon(memory,0,[(i*10,i*.25,0) for i in range(7)])
        row=reference(memory,9,0,residual=(2,1,-3))
        return SimpleNamespace(memory=memory,vehicles={9:row},core_paused=True)

    def test_straight_path_click_preserves_observed_render_residual(self):
        state=self.fixture()
        expected=profile.lane(state.memory,0,3.25,.72)['point']
        expected=[expected[k]+(2,1,-3)[k] for k in range(3)]
        before=dict(state.memory.data)
        result=placement.project_target(state,9,expected[0],expected[2])
        self.assertAlmostEqual(result['progression'],3.25,places=5)
        self.assertAlmostEqual(result['lateral'],.72,places=6)
        self.assertLess(result['error_distance'],1e-5)
        self.assertAlmostEqual(result['point'][1],expected[1],places=5)
        self.assertEqual((result['path'],result['reference_id']),(0,9))
        self.assertEqual(result['path_descriptor'],profile.PATHS)
        self.assertEqual((result['speed'],result['spacing']),(30,1.5))
        self.assertTrue(result['approximate'])
        self.assertEqual(state.memory.data,before)

    def test_curve_projection_uses_loaded_spline_not_straight_reference_tangent(self):
        state=self.fixture()
        centers=[(i*8,3+i*.3,(i-3)**2*2) for i in range(8)]
        ribbon(state.memory,1,centers,width=8)
        state.vehicles={4:reference(state.memory,4,1,progress=1.25,residual=(1,.7,-2))}
        expected=profile.lane(state.memory,1,5.37,.18)['point']
        expected=[expected[k]+(1,.7,-2)[k] for k in range(3)]
        result=placement.project_target(state,4,expected[0],expected[2])
        self.assertAlmostEqual(result['progression'],5.37,places=4)
        self.assertAlmostEqual(result['lateral'],.18,places=4)
        self.assertLess(result['error_distance'],1e-4)
        self.assertAlmostEqual(result['point'][1],expected[1],places=4)

    def test_normal_clamps_to_ribbon_while_experiment_extrapolates_across(self):
        state=self.fixture()
        normal=placement.project_target(state,9,32,32)
        experiment=placement.project_target(state,9,32,32,experimental=True)
        self.assertEqual(normal['lateral'],1)
        self.assertTrue(normal['clamped'])
        self.assertAlmostEqual(normal['error_distance'],30,places=4)
        self.assertAlmostEqual(experiment['lateral'],4,places=5)
        self.assertLess(experiment['error_distance'],1e-4)
        self.assertTrue(experiment['experimental'])
        self.assertFalse(experiment['clamped'])

    def test_search_without_selection_uses_only_observed_ready_paths(self):
        state=self.fixture()
        ribbon(state.memory,1,[(i*10,5,100) for i in range(7)])
        state.vehicles[5]=reference(state.memory,5,1)
        # A cold reference on a nearer, otherwise unreadable path is ignored.
        state.vehicles[2]=dict(state.vehicles[5],id=2,path=2,initialized=False)
        result=placement.project_target(state,None,25,102)
        self.assertEqual((result['path'],result['reference_id']),(1,5))
        self.assertLess(result['error_distance'],1e-4)
        # Choosing a reference explicitly never silently switches its path.
        chosen=placement.project_target(state,9,25,102)
        self.assertEqual(chosen['path'],0)
        self.assertGreater(chosen['error_distance'],90)

    def test_invalid_missing_cold_or_unloaded_reference_is_rejected(self):
        for change in ('missing','cold','unready','path','node'):
            with self.subTest(change=change):
                state=self.fixture()
                if change=='missing': state.vehicles.clear()
                elif change=='cold': state.vehicles[9]['initialized']=False
                elif change=='unready': state.vehicles[9]['can_reference']=False
                elif change=='path': state.vehicles[9]['path']=255
                else: state.vehicles[9]['node']=0
                with self.assertRaises(profile.ProfileError):
                    placement.project_target(state,9,10,0)

    def test_unknown_geometry_is_not_invented_or_substituted_for_selected_path(self):
        state=self.fixture()
        state.memory.store(profile.PATHS,'<I',0)
        with self.assertRaises(profile.ProfileError):
            placement.project_target(state,9,20,0)
        with self.assertRaises(profile.ProfileError):
            placement.project_target(state,None,20,0)

    def test_path_with_later_invalid_geometry_is_excluded_in_full(self):
        state=self.fixture()
        ribbon(state.memory,1,[(i*10,5,100) for i in range(7)])
        state.vehicles[5]=reference(state.memory,5,1)
        # Reference progress2 is still locally finite; a farther control point
        # is corrupt. Partial coarse results from that path must not survive.
        state.memory.store(0x101000+12*16,'<f',float('nan'))
        result=placement.project_target(state,None,25,0)
        self.assertEqual(result['path'],1)
        with self.assertRaises(profile.ProfileError):
            placement.project_target(state,9,25,0)

    def test_progression_remains_inside_loaded_path_even_in_experiment(self):
        state=self.fixture()
        result=placement.project_target(state,9,-1000,80,experimental=True)
        self.assertGreaterEqual(result['progression'],0)
        self.assertLessEqual(result['progression'],result['count']-1)
        self.assertGreater(result['error_distance'],900)

    def test_nonfinite_or_unrepresentable_coordinates_and_invalid_modes_rejected(self):
        state=self.fixture()
        for value in (True,'10',float('nan'),float('inf'),1e100):
            for axis in (0,1):
                with self.subTest(value=value,axis=axis):
                    args=[10,0]
                    args[axis]=value
                    with self.assertRaises(profile.ProfileError):
                        placement.project_target(state,9,*args)
        for experimental in (None,1,'yes'):
            with self.assertRaises(profile.ProfileError):
                placement.project_target(state,9,10,0,experimental=experimental)
        with self.assertRaises(profile.ProfileError):
            placement.project_target(state,True,10,0)

    def test_running_snapshot_and_all_cold_paths_are_rejected_without_memory_reads(self):
        state=self.fixture()
        state.core_paused=False
        state.memory=None
        with self.assertRaises(profile.ProfileError):
            placement.project_target(state,None,20,0)
        state.core_paused=True
        for row in state.vehicles.values(): row['initialized']=False
        with self.assertRaises(profile.ProfileError):
            placement.project_target(state,None,20,0)


if __name__=='__main__':
    unittest.main()
