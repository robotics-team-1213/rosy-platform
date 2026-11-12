"""Confluence board layout and contact-only acceptance for three long-bar layers."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET  # noqa: F401

import ship_plate
from pad_sweep import pad_sweep_bottom_relative_tcp, rotation_matrix  # noqa: F401  (split out, D-766)
from stack_spots import leveling_center, leveling_via, seat_check  # noqa: F401  (split out, D-766)
from stacking_fixture import DT, PROFILE  # noqa: F401
from release_cases import EVALUATION_CASES, FIXTURE_OVERRIDES, RL_RESIDUALS  # noqa: F401
from mapped_stack_fixture_helpers import (  # noqa: F401
    CONTAINER_REPORT_BYTES,
    CUBE_FIXTURE,
    CUBE_REPORT_BYTES,
    FIXTURE,
    RL_FIXTURE,
    ROOT,
    belt_transport_observed,
    check_massless_tcp,
    contact_names,
    container_fixture,
    explained_contacts,
    free_lift,
    grip_duration,
    half_extent,
    home,
    norm,
    physical_model,
    plan,
    source_height_observed,
    tcp_from_wrist,
    unsupported_hold,
)


def prefix_held(sample, index, fixture):
    """Placed boxes keep position, support and contacts; their speed is gated by prefix_window_observed."""
    return all(stable_box(sample['boxes'][j],j,True,fixture=fixture,speed=False) for j in range(index))


def measured_motion(samples):
    """Each box's velocity is its pose change since the previous sample over the elapsed ticks.
    Isaac's instantaneous cargo velocity is contact-solver chatter here: run b326 reported .18 rad/s while poses
    moved at most 6 um per 0.1 s, and run ce56 kept .014 m/s for 26 s at a fixed pose. samples[0] is the reference."""
    result = samples[:1]
    for prev, sample in zip(samples, samples[1:]):
        dt = (sample['tick']-prev['tick'])*DT
        boxes = []
        for a, b in zip(prev['boxes'], sample['boxes']):
            dot = min(1., abs(sum(x*y for x, y in zip(a['orientation'], b['orientation']))))
            boxes.append(dict(b, velocity=[(y-x)/dt for x, y in zip(a['position'], b['position'])],
                              angular_velocity=[2*math.acos(dot)/dt, 0., 0.]))
        result.append(dict(sample, boxes=boxes))
    return result


def window_observed(window, ok):
    """A reference sample, then twelve consecutive samples (the original 1.1s window) that pass `ok`."""
    try:
        return (len(window) == 13 and all(b['tick']-a['tick'] == 12 for a, b in zip(window, window[1:]))
            and all(ok(s) for s in measured_motion(window)[1:]))
    except (KeyError,TypeError,IndexError):
        return False


def prefix_window_observed(window, index, fixture, before_tick):
    """The prior stack holds the original stable window before the next release."""
    if not index:
        return window == []
    return (bool(window) and window[-1].get('tick', before_tick+1) <= before_tick
        and window_observed(window, lambda s: all(stable_box(s['boxes'][j],j,True,fixture=fixture) for j in range(index))))


def row_gaps(sample, fixture, placed=None):
    """Measured Y gap between each placed outer row and its center row on the same level."""
    items = plan(True,fixture=fixture)[:placed]
    centers = {item['cell'][2]: j for j, item in enumerate(items) if item['cell'][1] == fixture.get('center_row',1)}
    gaps = []
    for j, item in enumerate(items):
        c = centers.get(item['cell'][2])
        if c is None or j == c:
            continue
        direction = item['cell'][1]-fixture.get('center_row',1)
        outer, center = sample['boxes'][j], sample['boxes'][c]
        gaps.append(direction*(outer['position'][1]-center['position'][1])
            - half_extent(outer,item['size'],1) - half_extent(center,items[c]['size'],1))
    return gaps


def leveling_release_target(index, sample, fixture, commanded_tcp=None):
    arm = plan(True,fixture=fixture)[index]['arm']
    box = sample['boxes'][index]
    if not unsupported_hold(box,arm):
        raise ValueError('Leveling carry is not an unsupported bilateral hold')
    if not prefix_held(sample,index,fixture):
        raise ValueError('Previous pallet prefix moved before leveling release')
    center = leveling_center(fixture, arm)
    desired = [*center[:2],center[2]+.015+fixture['release_clearance_m']]
    anchor = sample['tcps'][arm] if commanded_tcp is None else commanded_tcp
    return [anchor[k]+desired[k]-box['position'][k] for k in range(3)]


def leveling_box_stable(box,index,fixture):
    size = plan(True,fixture=fixture)[index]['size']
    values = [*box['position'],*box['orientation'],*box['velocity'],*box['angular_velocity'],
              *box['net_force'],*(v for force in box['forces'] for v in force)]
    if not all(math.isfinite(v) for v in values) or abs(sum(v*v for v in box['orientation'])-1) > .01:
        return False
    table = contact_names(index,True,fixture=fixture).index('table')
    if (box['forces'][table][2] <= .001 or not explained_contacts(box)
            or any(norm(force) > .001 for j,force in enumerate(box['forces']) if j != table)
            or norm(box['velocity']) > .01 or norm(box['angular_velocity']) > .1
            or rotation_matrix(box['orientation'])[2][2] < math.cos(fixture['leveling_flat_tolerance_rad'])):
        return False
    center = leveling_center(fixture, plan(True,fixture=fixture)[index]['arm'])
    return (abs(box['position'][2]-center[2]-.015) <= .0015
        and all(abs(box['position'][axis]-center[axis])+half_extent(box,size,axis)
                <= fixture['leveling_size_m'][axis]/2 for axis in (0,1)))


def leveling_observed(stage,index,fixture):
    try:
        arm = plan(True,fixture=fixture)[index]['arm']
        settles,lifts,grasps = stage['settle_samples'],stage['lift_samples'],stage['grasp_samples']
        released = stage['release_sample']
        target = leveling_release_target(index,released,fixture)
        if (stage['arm'] != arm or norm([target[k]-released['tcps'][arm][k] for k in range(3)]) > .00005
                or not 10 <= len(settles) <= 30 or settles[-1]['tick']-settles[0]['tick'] < fixture['settle_steps']
                or not 3 <= len(lifts) <= 30 or lifts[-1]['tick']-lifts[0]['tick'] < 24 or len(grasps) != 2
                or not released['tick'] < stage['opened_sample']['tick'] <= settles[0]['tick']
                or not settles[-1]['tick'] <= grasps[0]['tick'] < grasps[1]['tick'] < lifts[0]['tick']
                or abs(stage['source_center_z']-settles[-1]['boxes'][index]['position'][2]) > .0015):
            return False
        for sample in settles:
            if (not leveling_box_stable(sample['boxes'][index],index,fixture)
                    or any(norm([tcp[k]-sample['boxes'][index]['position'][k] for k in range(3)]) < .04
                           for tcp in sample['tcps'])):
                return False
        return (all(free_lift(sample['boxes'][index],arm,stage['source_center_z']) for sample in lifts)
            and prefix_window_observed(stage['prefix_window'],index,fixture,released['tick'])
            and all(prefix_held(sample,index,fixture) for sample in [*settles,*lifts]))
    except (KeyError,TypeError,IndexError,ValueError):
        return False


def leveling_sequence_observed(layer,index,fixture):
    stage = layer.get('leveling')
    if not leveling_observed(stage,index,fixture):
        return False
    try:
        if not layer['lift_samples'][-1]['tick'] < stage['release_sample']['tick']:
            return False
        if 'release_sample' in layer and not stage['lift_samples'][-1]['tick'] < layer['release_sample']['tick']:
            return False
        if 'opened_sample' in layer and not layer['release_sample']['tick'] < layer['opened_sample']['tick']:
            return False
        return (not layer['settle_samples']
            or layer['opened_sample']['tick'] <= layer['settle_samples'][0]['tick'])
    except (KeyError,TypeError,IndexError):
        return False


def center_neighbor(index, sample, fixture):
    items = plan(True, fixture=fixture)
    level = items[index]['cell'][2]
    peers = [(sample['boxes'][j], item['size']) for j, item in enumerate(items[:index])
             if item['cell'][2] == level and item['cell'][1] == 1]
    if len(peers) != 1:
        raise ValueError('Outer placement requires its settled center row')
    body, size = peers[0]
    direction = items[index]['cell'][1]-1
    face = body['position'][1]+direction*half_extent(body, size, 1)
    return direction, face, body['position'][2]+half_extent(body, size, 2)


class PackingFootprintUnavailable(ValueError):
    """The measured held orientation cannot fit the original target envelope."""


def release_footprint_fits(box,size,y,fixture):
    extent=half_extent(box,size,1)
    overhang=fixture.get('transient_tilt_overhang_m',0.)
    flat=extent
    if overhang:
        w,x,qy,z=box['orientation']
        yaw=math.atan2(2*(w*z+x*qy),1-2*(qy*qy+z*z))
        flat=(abs(math.sin(yaw))*size[0]+abs(math.cos(yaw))*size[1])/2
    low=fixture['bin_origin_m'][1]-.001
    high=fixture['bin_origin_m'][1]+fixture['bin_size_m'][1]+.001
    return (y-flat>=low and y+flat<=high
        and y-extent>=low-overhang and y+extent<=high+overhang)


def finger_fits_gap(gap, fixture):
    # The neighbour-side finger may go down into the row gap only when the gap is wider than the finger needs.
    return gap >= fixture.get('finger_gap_width_m', math.inf)


def packed_release_position(index, sample, fixture):
    item = plan(True, fixture=fixture)[index]
    box = sample['boxes'][index]
    desired = item['target'][:]
    desired[2] += fixture.get('stack_release_clearance_m', fixture['release_clearance_m'])  # leveling keeps its own
    pad_offset = lambda: (sample['tcps'][item['arm']][2]-box['position'][2]  # noqa: E731  (finger bottom below the box centre)
        +pad_sweep_bottom_relative_tcp(sample['wrist_orientations'][item['arm']], fixture.get('gripper')))
    if fixture.get('ship_plate') and item['cell'][2] == 0:  # first layer: box and fingers stay above the studs
        desired[2] = max(desired[2], ship_plate.release_floor_z(fixture, pad_offset()))
    if item['cell'][1] == fixture.get('center_row',1):
        return desired
    direction, face, top = center_neighbor(index, sample, fixture)
    extent = half_extent(box, item['size'], 1)
    edge = face+direction*(extent+fixture['row_clearance_m'])
    desired[1] = min(desired[1], edge) if direction < 0 else max(desired[1], edge)
    if not release_footprint_fits(box,item['size'],desired[1],fixture):
        raise PackingFootprintUnavailable('Outer held footprint cannot fit the original envelope')
    if finger_fits_gap(direction*(desired[1]-face)-extent, fixture):
        return desired
    clearance = fixture['neighbor_vertical_clearance_m']
    # Measured lateral separation excludes body overlap; only swept fingers may need a higher release.
    desired[2] = max(desired[2], top+clearance-pad_offset())
    return desired


def cube_release_target(index, sample, source_z, commanded_tcp=None, *, fixture=None):
    fixture = CUBE_FIXTURE if fixture is None else fixture
    items = plan(True, fixture=fixture)
    item = items[index]
    box, arm = sample['boxes'][index], item['arm']
    # Lift height was proved during carry; lowering for placement still requires an unsupported bilateral hold.
    if not unsupported_hold(box, arm):
        raise ValueError('cube carry lost bilateral free lift before release')
    if fixture.get('packing_strategy'):
        desired = packed_release_position(index, sample, fixture)
        desired[:2] = [desired[k]+fixture.get('release_offset_m', (0., 0.))[k] for k in (0, 1)]  # deliberate off-centre release (MuJoCo sweep candidates)
        anchor = sample['tcps'][arm] if commanded_tcp is None else commanded_tcp
        return [anchor[k]+desired[k]-box['position'][k] for k in range(3)]
    desired = item['target'][:]
    desired[2] += fixture.get('stack_release_clearance_m', fixture['release_clearance_m'])  # leveling keeps its own
    if item['cell'][1] == 0:
        # Measured positive opening drift accumulates across tightly packed rows; center the released footprint.
        desired[1] += fixture['first_row_release_bias_m']
    if index % 3:
        def half_width(body):
            w, x, y, z = body['orientation']
            row = (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w))
            return sum(abs(row[k])*item['size'][k]/2 for k in range(3))
        neighbor = sample['boxes'][index-1]
        separation = half_width(neighbor)+half_width(box)+fixture['row_clearance_m']
        if items[index-1]['cell'][1] < item['cell'][1]:
            desired[1] = max(desired[1], neighbor['position'][1]+separation)
        else:
            desired[1] = min(desired[1], neighbor['position'][1]-separation)
    anchor = sample['tcps'][arm] if commanded_tcp is None else commanded_tcp
    return [anchor[k]+desired[k]-box['position'][k] for k in range(3)]


def cube_release_ready(index, sample, source_z, *, fixture=None):
    command = cube_release_target(index, sample, source_z, fixture=fixture)
    items = plan(True, fixture=fixture)
    tcp = sample['tcps'][items[index]['arm']]
    error = [command[k]-tcp[k] for k in range(3)]
    if fixture and fixture.get('packing_strategy'):
        clear = True
        if items[index]['cell'][1] != fixture.get('center_row',1):
            direction, face, top = center_neighbor(index, sample, fixture)
            box = sample['boxes'][index]
            y_extent = half_extent(box, items[index]['size'], 1)
            margin = fixture['row_clearance_m']-.000001
            vertical = fixture['neighbor_vertical_clearance_m']-.000001
            gap = direction*(box['position'][1]-face)-y_extent
            clear = (gap >= margin
                and release_footprint_fits(box,items[index]['size'],box['position'][1],fixture)
                and (finger_fits_gap(gap, fixture) or
                     tcp[2]+pad_sweep_bottom_relative_tcp(sample['wrist_orientations'][items[index]['arm']], fixture.get('gripper')) >= top+vertical))
        # Estimate-only control converges to its estimate, not the true pose: estimate cases accept the final
        # position tolerance here; clearance, footprint and prior-stack checks stay on the measured pose.
        return norm(error) <= fixture.get('release_convergence_m', .00005) and clear and prefix_held(sample, index, fixture)
    direction = 1 if index % 3 == 0 or items[index-1]['cell'][1] < items[index]['cell'][1] else -1
    return (norm(error) <= .00005 and (index % 3 == 0 or direction*error[1] <= .000001)
            and all(stable_box(sample['boxes'][j], j, True, fixture=fixture) for j in range(index)))


def stable_box(box, index, cube=False, *, fixture=None, speed=True):
    items = plan(cube, fixture=fixture)
    fixture = (CUBE_FIXTURE if cube else FIXTURE) if fixture is None else fixture
    item = items[index]
    p, q, forces = box['position'], box['orientation'], box['forces']
    values = [*p, *q, *box['velocity'], *box['angular_velocity'], *(v for row in forces for v in row)]
    if not all(math.isfinite(v) for v in values) or abs(sum(v*v for v in q)-1) > .01:
        return False
    # On the stud plate a box resting on a stud sits 0.9-1.2 mm high (Isaac offset runs 2026-11-01), inside the 1.5 mm band.
    tolerance = (.0015, .0015, .0005 if fixture.get('ship_plate') else .0015)
    if (any(abs(p[i]-item['target'][i]) > tolerance[i] for i in range(3))
            or speed and (norm(box['velocity']) > .01 or norm(box['angular_velocity']) > .1)
            or any(norm(f) > .001 for f in forces[:4]) or not explained_contacts(box)):
        return False
    width = len(fixture.get('row_order',[0,1,2])) if cube else 1
    below = 'bin' if index < width else items[index-width]['id']
    if forces[contact_names(index, cube, fixture=fixture).index(below)][2] <= .001:
        return False
    w, x, y, z = q
    matrix = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
              (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
              (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    for axis in range(3):
        extent = sum(abs(matrix[axis][j])*item['size'][j]/2 for j in range(3))
        low = fixture['bin_origin_m'][axis]
        if p[axis]-extent < low-.001 or p[axis]+extent > low+fixture['bin_size_m'][axis]+.001:
            return False
    return True


def judge(trial, cube=False, *, fixture=None):
    failures = []
    layers = trial.get('layers', [])
    if len(layers) != len(plan(cube, fixture=fixture)):
        return dict(task_success=False, failures=['first_layer_not_completed' if cube else 'three_layers_not_completed'])
    for i, layer in enumerate(layers):
        if 'policy' in layer:  # D-969: a learned policy is judged on the outcome only (where the boxes settled)
            if layer.get('item') != i or layer.get('arm') != plan(cube, fixture=fixture)[i]['arm']:
                failures.append(f'layer_{i+1}:wrong_item_or_arm')
            settles = layer.get('settle_samples', [])
            if len(settles) < 10 or not all(stable_box(s['boxes'][j], j, cube, fixture=fixture) for s in settles for j in range(i+1)):
                failures.append(f'layer_{i+1}:policy_box_not_settled_at_target')
            continue
        if fixture and fixture.get('leveling_protocol') and not leveling_sequence_observed(layer,i,fixture):
            failures.append(f'layer_{i+1}:leveling_or_regrasp_not_observed')
        if layer.get('item') != i or layer.get('arm') != plan(cube, fixture=fixture)[i]['arm']:
            failures.append(f'layer_{i+1}:wrong_item_or_arm')
        lifts, settles = layer.get('lift_samples', []), layer.get('settle_samples', [])
        if len(lifts) < 3 or lifts[-1]['tick']-lifts[0]['tick'] < 24:
            failures.append(f'layer_{i+1}:lift_not_observed')
        else:
            for sample in lifts:
                box = sample['boxes'][i]
                forces = box['forces']
                arm = plan(cube, fixture=fixture)[i]['arm']
                if not free_lift(box, arm, layer['source_center_z']):
                    failures.append(f'layer_{i+1}:no_bilateral_free_lift')
                    break
        if len(settles) < 10 or settles[-1]['tick']-settles[0]['tick'] < FIXTURE['settle_steps']:
            failures.append(f'layer_{i+1}:settle_not_observed')
        else:
            # Packed releases record a reference sample first; see measured_motion.
            packed = bool(fixture and fixture.get('packing_strategy'))
            for sample in (measured_motion(settles)[1:] if packed else settles):
                if (not all(stable_box(sample['boxes'][j], j, cube, fixture=fixture) for j in range(i+1))
                        or any(norm([tcp[k]-sample['boxes'][j]['position'][k] for k in range(3)]) < .04
                               for tcp in sample['tcps'] for j in range(i+1))):
                    failures.append(f'layer_{i+1}:release_support_or_retreat_failed')
                    break
        if (fixture and fixture.get('leveling_protocol') and fixture.get('packing_strategy')
                and not prefix_window_observed(layer.get('prefix_window'),i,fixture,
                                               layer.get('release_sample',{}).get('tick',-1))):
            failures.append(f'layer_{i+1}:prior_stack_window_not_observed')
    band = fixture.get('row_gap_band_m') if fixture else None
    if band and not failures:
        final = layers[-1]['settle_samples'][-1]
        if not all(band[0]-1e-6 <= gap <= band[1]+1e-6 for gap in row_gaps(final, fixture)):
            failures.append('row_gap_outside_band')
    return dict(task_success=not failures, failures=failures)
