"""Bounded, read-only drawing data for loaded native traffic-path ribbons.

The ribbons are the researched traffic splines, not a mesh of the road or a
navigation graph for the player. Arrows show increasing spline progression;
traffic flow is marked verified only where a moving reference corroborates it.
"""
from __future__ import annotations

import math
import struct

from . import profile
from .pine import RAM_SIZE


DEFAULT_POINT_BUDGET = 2048
DEFAULT_READ_BUDGET = 4*1024*1024
MAX_POINT_BUDGET = 8192
MAX_POINTS_PER_PATH = 256
PATH_COUNT = 255


class _ReadBudgetExceeded(profile.ProfileError):
    pass


class _BudgetMemory:
    """Check additional cached-page cost before the underlying memory read."""
    def __init__(self, memory, budget):
        self.memory, self.budget = memory, budget
        self.cached = isinstance(memory,profile.CachedMemory)
        self.start = memory.bytes_fetched if self.cached else 0
        self.requested = 0

    @property
    def used(self):
        return self.memory.bytes_fetched-self.start if self.cached else self.requested

    def read_bytes(self,address,size):
        profile.CachedMemory._bounds(address,size)
        cost = size
        if self.cached:
            if any(start <= address and address+size <= start+len(data)
                   for start,data in self.memory._regions):
                cost = 0
            else:
                first = address & ~0xFFF
                last = min(RAM_SIZE,(address+size+0xFFF)&~0xFFF)
                cost = last-first
        if self.used+cost > self.budget:
            raise _ReadBudgetExceeded('The path read budget was reached.')
        if not self.cached:
            self.requested += cost
        if hasattr(self.memory,'read_bytes'):
            return self.memory.read_bytes(address,size)
        return self.memory.read(address,f'<{size}s')[0]

    def read(self,address,format_):
        if not format_.startswith('<'):
            raise profile.ProfileError('Invalid read format.')
        return struct.unpack(format_,self.read_bytes(address,struct.calcsize(format_)))

    def u8(self,address): return self.read(address,'<B')[0]
    def u32(self,address): return self.read(address,'<I')[0]
    def xyz(self,address): return list(self.read(address,'<3f'))


_INVALID = (profile.ProfileError,KeyError,TypeError,ValueError,OverflowError,struct.error)


def _point(values):
    point = [float(v) for v in values]
    if len(point) != 3 or not all(math.isfinite(v) for v in point):
        raise profile.ProfileError('The path contains invalid coordinates.')
    try:
        packed = struct.pack('<3f',*point)
    except (OverflowError,struct.error) as error:
        raise profile.ProfileError('Path coordinate exceeds float32.') from error
    if not all(math.isfinite(v) for v in struct.unpack('<3f',packed)):
        raise profile.ProfileError('Path coordinate exceeds float32.')
    return point


def _references(state):
    by_path = {}
    for row in state.vehicles.values():
        path = row.get('path')
        if type(path) is int and 0 <= path < PATH_COUNT and row.get('node'):
            by_path.setdefault(path,[]).append(row)
    for rows in by_path.values(): rows.sort(key=lambda row:row['id'])
    return by_path


def _header(memory,path):
    descriptor = profile.PATHS+path*profile.PATH_STRIDE
    if descriptor+profile.PATH_STRIDE > profile.MANAGER or memory.u8(descriptor+0x47) != path:
        raise profile.ProfileError('Descritor sem identidade correspondente.')
    geometry = memory.u32(descriptor)
    if not 0 < geometry <= RAM_SIZE-0x14:
        raise profile.ProfileError('Geometry missing or outside memory.')
    pairs,vertices,count = memory.u32(geometry),memory.u32(geometry+0xC),memory.u32(geometry+0x10)
    if not 2 <= count <= 65536 or not 0 < pairs <= RAM_SIZE-count*4 or not 0 < vertices <= RAM_SIZE-16:
        raise profile.ProfileError('Geometry tables out of bounds.')
    # The actual spline evaluator verifies each sampled vertex address.
    profile.lane(memory,path,0.,.5)
    return dict(id=path,count=count,descriptor=descriptor)


def _verified_flow(memory,path,rows):
    for row in rows:
        if (not row.get('can_reference') or not row.get('initialized')
                or type(row.get('travel_speed')) not in (int,float)
                or not math.isfinite(row['travel_speed']) or row['travel_speed'] <= 0):
            continue
        node = row.get('node')
        if type(node) is not int:
            continue
        index = profile.index_for_pointer(node,profile.NODES,profile.NODE_STRIDE)
        if index is None:
            continue
        try:
            forward = memory.xyz(profile.MATRICES+index*profile.MATRIX_STRIDE+0x20)
            derivative = profile.lane(memory,path,row['progress'],row['lateral'])['derivative']
            denominator = math.sqrt(sum(v*v for v in forward))*math.sqrt(sum(v*v for v in derivative))
            if denominator > 1e-9 and sum(a*b for a,b in zip(forward,derivative))/denominator >= .5:
                return True
        except _ReadBudgetExceeded:
            raise
        except _INVALID:
            continue
    return False


def _sample(memory,header,samples,rows):
    path,count = header['id'],header['count']
    left,center,right = [],[],[]
    arrow_indexes = sorted({max(0,min(samples-1,round((samples-1)*fraction)))
                            for fraction in (.25,.5,.75)})
    arrows = []
    for index in range(samples):
        progress = (count-1)*index/(samples-1)
        geometry = profile.lane(memory,path,progress,0.)
        a = _point(geometry['point'])
        b = _point(a[k]+geometry['lane'][k] for k in range(3))
        middle = _point((a[k]+b[k])/2 for k in range(3))
        left.append(a)
        center.append(middle)
        right.append(b)
        if index in arrow_indexes:
            other = profile.lane(memory,path,progress,1.)
            derivative = [(geometry['derivative'][k]+other['derivative'][k])/2 for k in range(3)]
            horizontal = math.hypot(derivative[0],derivative[2])
            if math.isfinite(horizontal) and horizontal > 1e-9:
                length = min(8.,max(1.5,geometry['width']*.6))
                arrows.append({'from':list(middle),
                    'to':_point(middle[k]+length*derivative[k]/horizontal for k in range(3))})
    direction_limited = False
    try:
        verified = _verified_flow(memory,path,rows)
    except _ReadBudgetExceeded:
        # Optional flow corroboration must not discard a fully sampled ribbon.
        verified,direction_limited = False,True
    return dict(id=path,descriptor=header['descriptor'],control_point_count=count,
        left=left,center=center,right=right,arrows=arrows,
        vehicle_ids=[row['id'] for row in rows],sample_count=samples,
        source='vehicle_reference' if rows else 'descriptor_candidate',
        reference_observed=bool(rows),
        approximate=True,sampled_geometry=True,
        direction_label='Path progression',
        traffic_direction_verified=verified,direction_verification_limited=direction_limited)


def build_network(state, *, point_budget=DEFAULT_POINT_BUDGET,
                  read_budget=DEFAULT_READ_BUDGET,scan_unreferenced=True):
    """Return JSON-ready ribbons under global sampling and memory budgets.

    ``point_budget`` counts center samples; each also has a left/right point.
    ``read_budget`` bounds additional pages for CachedMemory, or requested bytes
    for a generic read-only adapter. Incomplete/invalid paths are omitted whole.
    Unreferenced descriptors require the same identity, table and sampled-vertex
    checks; their presence does not establish connectivity or drivability.
    """
    if getattr(state,'core_paused',True) is not True:
        raise profile.ProfileError('Pause PCSX2 before reading the paths.')
    if type(point_budget) is not int or not 2 <= point_budget <= MAX_POINT_BUDGET:
        raise profile.ProfileError('Use a budget of 2 to 8192 path samples.')
    if type(read_budget) is not int or not 1 <= read_budget <= 8*1024*1024:
        raise profile.ProfileError('Invalid path read budget.')
    if type(scan_unreferenced) is not bool:
        raise profile.ProfileError('Invalid path discovery option.')
    memory = _BudgetMemory(state.memory,read_budget)
    refs = _references(state)
    order = sorted(refs)
    if scan_unreferenced: order += [path for path in range(PATH_COUNT) if path not in refs]
    candidates,omitted = [],[]
    truncated = False
    scan_complete = True
    for path in order:
        if len(candidates) >= point_budget//2:
            truncated,scan_complete = True,False
            break
        try:
            candidates.append(_header(memory,path))
        except _ReadBudgetExceeded:
            truncated,scan_complete = True,False
            break
        except _INVALID:
            if path in refs: omitted.append(path)
    allocations = {row['id']:2 for row in candidates}
    remaining = point_budget-2*len(candidates)
    while remaining:
        advanced = False
        for row in candidates:
            desired = min(MAX_POINTS_PER_PATH,max(2,row['count']*4))
            if allocations[row['id']] < desired:
                allocations[row['id']] += 1
                remaining -= 1
                advanced = True
                if not remaining: break
        if not advanced: break
    paths = []
    for position,header in enumerate(candidates):
        try:
            rendered = _sample(memory,header,allocations[header['id']],refs.get(header['id'],[]))
            paths.append(rendered)
            if rendered['direction_verification_limited']:
                truncated = True
                omitted.extend(row['id'] for row in candidates[position+1:])
                break
        except _ReadBudgetExceeded:
            truncated = True
            omitted.extend(row['id'] for row in candidates[position:])
            break
        except _INVALID:
            omitted.append(header['id'])
    points = [p for path in paths for side in ('left','center','right') for p in path[side]]
    bounds = ({'min':[min(p[k] for p in points) for k in range(3)],
               'max':[max(p[k] for p in points) for k in range(3)]} if points else None)
    xz_bounds = [bounds['min'][0],bounds['min'][2],bounds['max'][0],bounds['max'][2]] if bounds else None
    warning = ('Partial view: path budget reached.' if truncated else '')
    if omitted:
        warning += (' ' if warning else '')+'Paths with incomplete or invalid data were left out.'
    unreferenced = sum(not path['reference_observed'] for path in paths)
    if unreferenced:
        warning += (' ' if warning else '')+'Includes descriptors with no reference vehicle; the current use of these paths was not confirmed.'
    return dict(paths=paths,bounds=bounds,xz_bounds=xz_bounds,
        point_budget=point_budget,sample_count=sum(path['sample_count'] for path in paths),
        read_bytes=memory.used,read_budget=read_budget,
        read_metric='additional_cached_bytes' if memory.cached else 'requested_bytes',
        omitted_path_ids=sorted(set(omitted)),truncated=truncated,
        unreferenced_path_count=unreferenced,
        scan_complete=scan_complete,approximate=True,warning=warning,
        direction_label='Arrows show the direction of travel along the path; they do not show connections between lanes.')
