"""Read-only projection of a map click onto observed loaded traffic paths.

The result is an approximate ribbon projection for a stock-engine creation.
It does not teleport an existing rigid body, find terrain, write memory or
admit paths that have no initialized reference in the snapshot.
"""
from __future__ import annotations

import math
import struct

from . import profile


COARSE_BUDGET = 4096
MAX_STEPS_PER_PATH = 512
REFINE_CANDIDATES = 4
REFINE_STEPS = 40


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise profile.ProfileError(f'{label} must be a finite number.')
    try:
        rounded = struct.unpack('<f', struct.pack('<f', value))[0]
    except (OverflowError, struct.error) as error:
        raise profile.ProfileError(f"{label} is outside the game's numeric range.") from error
    if not math.isfinite(rounded):
        raise profile.ProfileError(f"{label} is outside the game's numeric range.")
    return float(value)


def _references(state, reference_id, x, z):
    if reference_id is not None and type(reference_id) is not int:
        raise profile.ProfileError('Select a valid reference for the placement.')
    if reference_id is not None:
        row = state.vehicles.get(reference_id)
        if not row or not row.get('can_reference') or not row.get('initialized'):
            raise profile.ProfileError('The reference needs an initialized path and physics.')
        rows = [row]
    else:
        rows = [row for row in state.vehicles.values()
                if row.get('can_reference') and row.get('initialized')]
    # One observed reference per path. Its render-to-spline residual keeps the
    # map estimate in the same coordinate convention as the existing editor.
    paths = {}
    for row in rows:
        path = row.get('path')
        position = row.get('position')
        if (type(path) is not int or not 0 <= path < 255 or not row.get('node')
                or row.get('path_valid') is False or not isinstance(position,(list,tuple))
                or len(position) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in position)):
            if reference_id is not None:
                raise profile.ProfileError('The reference has no valid loaded path.')
            continue
        rank = (math.hypot(position[0]-x,position[2]-z),row['id'])
        if path not in paths or rank < paths[path][0]:
            paths[path] = (rank,row)
    if not paths:
        raise profile.ProfileError('No path has a reference with initialized physics.')
    return [paths[path][1] for path in sorted(paths)]


def project_target(state, reference_id, x, z, *, experimental=False):
    """Project X/Z onto an observed path, returning native-creation parameters.

    An explicit reference restricts the search to its path. ``None`` considers
    unique paths with initialized references, including stopped traffic. Normal mode clamps to the
    loaded ribbon; experimental mode extrapolates its cross-road vector. Both
    keep progression inside loaded geometry, use its Y, and require float32-
    representable results. No terrain or collision-free placement is implied.

    Search is bounded and numeric, so ``approximate`` is always true. The error
    reports distance between the click and the estimated resulting X/Z; callers
    should display that projection instead of promising unrestricted placement.
    """
    x,z = _number(x,'X'),_number(z,'Z')
    if type(experimental) is not bool:
        raise profile.ProfileError('Experimental mode must be on or off.')
    if getattr(state,'core_paused',True) is not True:
        raise profile.ProfileError('Pause PCSX2 before choosing the position.')
    rows = _references(state,reference_id,x,z)
    steps_budget = max(8,COARSE_BUDGET//len(rows))
    coarse = []
    failures = []
    evaluations = 0

    def evaluate(context,progress):
        nonlocal evaluations
        evaluations += 1
        geometry = profile.lane(state.memory,context['path'],progress,0.0)
        left = [geometry['point'][k]+context['residual'][k] for k in range(3)]
        across = geometry['lane']
        divisor = across[0]**2+across[2]**2
        if not math.isfinite(divisor) or divisor <= 1e-12:
            raise profile.ProfileError('The path has no usable width in the X/Z map.')
        raw_lateral = ((x-left[0])*across[0]+(z-left[2])*across[2])/divisor
        lateral = raw_lateral if experimental else max(0.0,min(1.0,raw_lateral))
        point = [left[k]+lateral*across[k] for k in range(3)]
        if not all(math.isfinite(v) for v in point+[lateral]):
            raise profile.ProfileError('The projection exceeded the admitted numeric range.')
        distance = math.hypot(x-point[0],z-point[2])
        return dict(distance=distance,progress=progress,lateral=lateral,
                    raw_lateral=raw_lateral,point=point,context=context)

    for row in rows:
        try:
            geometry = profile.lane(state.memory,row['path'],row['progress'],row['lateral'])
            context = dict(path=row['path'],row=row,count=geometry['count'],
                residual=[row['position'][k]-geometry['point'][k] for k in range(3)])
            context['step'] = (geometry['count']-1)/min(geometry['count']-1,steps_budget,MAX_STEPS_PER_PATH)
            steps = min(geometry['count']-1,steps_budget,MAX_STEPS_PER_PATH)
            samples = []
            for index in range(steps+1):
                samples.append(evaluate(context,(geometry['count']-1)*index/steps))
            coarse.extend(samples)
        except (KeyError,TypeError,ValueError,OverflowError) as error:
            if reference_id is not None:
                if isinstance(error,profile.ProfileError): raise
                raise profile.ProfileError("The reference's data does not allow projecting the position.") from error
            failures.append(str(error))
    if not coarse:
        detail = failures[0] if failures else 'Nenhuma geometria admitida.'
        raise profile.ProfileError('Could not project the position: '+detail)
    coarse.sort(key=lambda result:(result['distance'],result['context']['path'],result['progress']))
    best = coarse[0]
    # Refine several coarse neighborhoods, including path endpoints. This is
    # deliberately an estimate, not a proof of the global minimum on a loop.
    # Give distinct nearby paths a refinement before spending all brackets on
    # adjacent coarse samples from one road at an intersection.
    candidates,seen_paths = [],set()
    for initial in coarse:
        path = initial['context']['path']
        if path not in seen_paths:
            candidates.append(initial)
            seen_paths.add(path)
        if len(candidates) >= REFINE_CANDIDATES: break
    candidates.extend(coarse)
    brackets = set()
    for initial in candidates:
        context = initial['context']
        lo,hi = max(0.0,initial['progress']-context['step']),min(context['count']-1,initial['progress']+context['step'])
        key = (context['path'],lo,hi)
        if key in brackets: continue
        brackets.add(key)
        for _ in range(REFINE_STEPS):
            a,b = lo+(hi-lo)/3,hi-(hi-lo)/3
            left,right = evaluate(context,a),evaluate(context,b)
            if left['distance'] < best['distance']: best=left
            if right['distance'] < best['distance']: best=right
            if left['distance'] <= right['distance']: hi=b
            else: lo=a
        if len(brackets) >= REFINE_CANDIDATES: break
    context,row = best['context'],best['context']['row']
    progress = struct.unpack('<f',struct.pack('<f',best['progress']))[0]
    lateral = struct.unpack('<f',struct.pack('<f',_number(best['lateral'],'Lateral position')))[0]
    final = evaluate(context,min(context['count']-1,max(0.0,progress)))
    # Quantize the fraction used by a future node write, then recompute the
    # displayed point with that same value rather than a double-only estimate.
    geometry = profile.lane(state.memory,context['path'],final['progress'],0.0)
    point = [geometry['point'][k]+context['residual'][k]+lateral*geometry['lane'][k] for k in range(3)]
    for value,label in zip(point,('X','Y','Z')): _number(value,label)
    other = profile.lane(state.memory,context['path'],final['progress'],1.0)
    derivative = [(1-lateral)*geometry['derivative'][k]+lateral*other['derivative'][k] for k in range(3)]
    if not all(math.isfinite(v) for v in derivative) or math.sqrt(sum(v*v for v in derivative)) <= 1e-9:
        raise profile.ProfileError('The path has no usable orientation at the chosen position.')
    speed,spacing = _number(row['speed'],'Speed'),_number(row['spacing_scalar'],'Spacing')
    if not 0 <= speed <= 240 or not 0 <= spacing <= 10000:
        raise profile.ProfileError("The reference's native parameters are outside the admitted range.")
    return dict(path=context['path'],progression=final['progress'],lateral=lateral,
        point=point,error_distance=math.hypot(x-point[0],z-point[2]),
        requested_point=[x,z],reference_id=row['id'],descriptor=geometry['descriptor'],
        path_descriptor=geometry['descriptor'],speed=speed,spacing=spacing,
        residual=list(context['residual']),derivative=derivative,
        approximate=True,clamped=not experimental and not 0 <= best['raw_lateral'] <= 1,
        experimental=experimental,evaluations=evaluations,count=context['count'])
