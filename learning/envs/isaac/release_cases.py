"""Pinned release-corrector evaluation and RL cases (split from mapped_stack_fixture, D-766)."""
import math

from container_variants import MASS_RATIO
from palletizing_gripper import WRIST_CAMERA_B
from ship_plate import SHIP_PLATE

EVALUATION_CASES = {  # nominal geometry; the release feedback sees a 2-5 mm held-box estimate error
    'nominal-estimate': None,
    'nominal-bc-v0': dict(file='release-corrector-bc-v0.npz',
                          sha256='85713c8ec54190e53729d6df73d5d59f3e6e7d715058bfb7698b3793042b9294'),
    'nominal-bc-v0-rl0': dict(file='release-corrector-bc-v0.npz',
                              sha256='85713c8ec54190e53729d6df73d5d59f3e6e7d715058bfb7698b3793042b9294')}
EVALUATION_CASES['release-episodes-rl0'] = EVALUATION_CASES['nominal-bc-v0']
# RL iterations add a pinned residual and Gaussian exploration (metres) to the BC corrector.
RL_RESIDUALS = {'nominal-bc-v0-rl0': dict(file='release-residual-rl0.npz',
    sha256='c44398fffbefca6bba7ec6e7c7d16895dcab272c6394d4d9e16ea00f66ea0f72', sigma_m=.0002)}
RL_RESIDUALS['release-episodes-rl0'] = RL_RESIDUALS['nominal-bc-v0-rl0']
# rl1: one REINFORCE step on 135 decisions from episode runs 29b7 and 1f81 (rl0: 16/20 episodes settled).
EVALUATION_CASES['release-episodes-rl1'] = EVALUATION_CASES['nominal-bc-v0']
RL_RESIDUALS['release-episodes-rl1'] = dict(file='release-residual-rl1.npz',
    sha256='cf84c0a0d2a878eb072b37b2f2428a315e54899887db583314fbe878739036ed', sigma_m=.0002)
# 0.5 mm exploration on top of the v0 model's ~1 mm residual error pushed the first release past the 1.5 mm
# convergence tolerance (run 3d52), so no decision was recorded.
# rl2: rl1's data again from rl0 inside a 0.2 mm trust region (rl1 itself blocked 31 of 32 episodes, run 9968).
EVALUATION_CASES['release-episodes-rl2'] = EVALUATION_CASES['nominal-bc-v0']
RL_RESIDUALS['release-episodes-rl2'] = dict(file='release-residual-rl2.npz',
    sha256='bb424ece0730ab37b16a8e5dcc43febfeb45070fcd5e3f255eb36680f070c935', sigma_m=.0002)
# rl3: four rl0 episode runs (29b7, 1f81, 65e5, b31e; 261 decisions) from rl0 inside the same trust region.
EVALUATION_CASES['release-episodes-rl3'] = EVALUATION_CASES['nominal-bc-v0']
RL_RESIDUALS['release-episodes-rl3'] = dict(file='release-residual-rl3.npz',
    sha256='cde882834ab9f110d954c990eae4795446851924dcbe1a88822560358577febc', sigma_m=.0002)
# Nine-container check of rl3 without exploration: the same flow as nominal-bc-v0 (run ebdd, 8/9).
EVALUATION_CASES['nominal-bc-v0-rl3'] = EVALUATION_CASES['nominal-bc-v0']
RL_RESIDUALS['nominal-bc-v0-rl3'] = dict(RL_RESIDUALS['release-episodes-rl3'], sigma_m=0.)
# Seed 45 (run ffb0): box 0 fell the 15 mm release clearance and slid 7.4 mm on landing. Same flow released 8 mm up.
EVALUATION_CASES['nominal-bc-v0-release8'] = EVALUATION_CASES['nominal-bc-v0']
FIXTURE_OVERRIDES = {'nominal-bc-v0-release8': dict(release_clearance_m=.008)}
# Nominal IK (true pose) with a 3 mm release. The sim pad is a 3 mm capsule with a 1 mm rest offset per side, so a
# neighbour-side finger needs a 5 mm gap; the new real fingers are about 3 mm (side camera estimate, 2026-10-31).
FIXTURE_OVERRIDES['nominal-release3'] = dict(stack_release_clearance_m=.003)  # leveling stays at 15 mm (runs bcb1..4b67)
FIXTURE_OVERRIDES['nominal-gap6-release3'] = dict(stack_release_clearance_m=.003, finger_gap_width_m=.005, row_gap_m=.006,
                                                row_gap_band_m=[.0045, .0075])
# Opt-in palletizing jaw v2.1 (team CAD, 2026-10-31) and the real container masses (user, 2026-11-01: 1/2/3 cells
# 7.2 / 11.79 / 16 g). Everything else is the nominal flow; the default cases keep the stock jaw and 60 g.
FIXTURE_OVERRIDES['nominal-palletizing-v21'] = dict(gripper='palletizing-v2.1', tcp_offset_m=[.074, -.0016, 0.],
                                                    cargo_mass_kg=[.0072, .01179, .016])
# Step 1 check: pick one 3-cell container, lift it and hold 2 s; the run ends there on purpose.
FIXTURE_OVERRIDES['nominal-palletizing-v21-hold'] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21'], grasp_hold_check=True)
# Step 2 check: the same jaw on the navy stud plate (ship_plate.py; KAN-108 CAD since 2026-11-01, before that photo estimates with a
# 35.1 mm pitch and 5.1 mm lane). The three rows sit at the 36 mm dot pitch (6 mm lane); the stack release is 5 mm over the plate,
# above the 3 mm dots (the floor is enforced too).
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21'],
    ship_plate=dict(SHIP_PLATE), row_gap_m=.006, row_gap_band_m=[.0045, .0075], finger_gap_width_m=.005,
    stack_release_clearance_m=.005,
    # Open only 33 mm: each pad moves 1.5 mm off the box, so the neighbour-side pad (1.5 mm thick) stays inside the 5.1 mm lane (a 40 mm
    # opening swung it 5 mm outward into the centre box: layer-1 row gap -0.7 mm, run s42o).
    release_gap_m=.033,
    # Leveling goes to bare table past the bow, at the arms' reach limit: 0.212 m carry is unreachable there, so it
    # climbs and descends through a waypoint and carries at 0.13 m (planner scan, both arms reachable up to x -0.13, so the spot sits at -0.12 for drift margin).
    leveling_center_m=[-.12, 0., .072], leveling_size_m=[.10, .06], leveling_carry_height_m=.13, leveling_via_m=[-.07, 0., .212])
# Deliberate off-centre releases (release_offset_m = [along x, across y] metres, added to every placement's release target,
# after the neighbour clamp). Candidates from the MuJoCo sweep (tools/sim/ship_release_sweep.py, docs/validation/omx-palletizing-sim-2026-11-01):
# its layer-1 seat boundary at friction 1.0 is 0.5-0.6 mm across the channel and does not depend on the along offset. The sweep
# says y040 seats, y060 and y-060 ride up a stud on the first layer, x150 seats. MuJoCo picks these; only the Isaac result counts.
for _name, _offset in (('y040', [0., .0004]), ('y050', [0., .0005]), ('y060', [0., .0006]), ('y-060', [0., -.0006]),
                       ('x150', [.0015, 0.]), ('y020', [0., .0002]), ('y030', [0., .0003]), ('x100', [.001, 0.])):
    # Isaac 2026-11-01: y040..y-060 left first-layer boxes 0.9-1.2 mm high on a stud; x150 sits at the 1.5 mm target band edge.
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-'+_name] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'],
                                                                    release_offset_m=_offset)
# Isaac y020/y030 (2026-11-01): the 33 mm opening pushed a box released 0.2 mm toward its neighbour 0.6 mm outward onto
# the outer stud. Try a 31.5 mm opening (each pad 0.75 mm off the box) on the nominal and offset releases.
for _name, _offset in (('y-020', [0., -.0002]), ('y-030', [0., -.0003])):  # outward: meets the outer stud directly
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-'+_name] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'],
                                                                    release_offset_m=_offset)
for _name in ('', '-y020', '-y030', '-y040', '-y-020', '-y-030'):
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'+_name+'-g315'] = dict(
        FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'+_name], release_gap_m=.0315)
# 31.5 mm (2026-11-01, seed 42): nominal, y020 and y040 9/9; y030 and y-020 left the first box 1.3 mm high with a pad
# still touching it. Try the middle, 32.25 mm (each pad 1.1 mm off the box).
for _name in ('', '-y020', '-y030', '-y040', '-y-020'):
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'+_name+'-g3225'] = dict(
        FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'+_name], release_gap_m=.03225)
# Step 4 (2026-11-01, KAN-108 plate with 0.4 mm clearance per side): release strategy and container variant candidates from the MuJoCo
# strategy sweep (tools/sim/ship_release_strategy_sweep.py): a relief foot (bottom 3 mm narrowed to 29.0 mm, container_variants 'r290')
# widens the seat band most; a guarded descent (guarded_release.py) helps little. Isaac confirms the boundary only.
GUARDED_DESCENT = dict(step_m=.0005, limit_m=.008, stall_m=.0002)
for _name, _offset, _guard, _variant in (('y060-g315', .0006, False, None), ('y060-guard-g315', .0006, True, None),
                                         ('r290-g315', 0., False, 'r290'), ('y080-r290-g315', .0008, False, 'r290'),
                                         ('y100-r290-guard-g315', .001, True, 'r290'),
                                         # plain boundary on the CAD plate and the relief foot past 0.8 mm both ways
                                         ('y050-g315', .0005, False, None), ('y100-r290-g315', .001, False, 'r290'),
                                         ('y-080-r290-g315', -.0008, False, 'r290')):
    _value = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'], release_gap_m=.0315)
    if _offset:
        _value['release_offset_m'] = [0., _offset]
    if _guard:
        _value['guarded_descent'] = dict(GUARDED_DESCENT)
    if _variant:  # same density as the 16 g container: the mass follows the volume
        _value.update(container_variant=_variant, cargo_mass_kg=[round(m*MASS_RATIO[_variant], 7) for m in _value['cargo_mass_kg']])
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-'+_name] = _value
# Yaw at release (2026-11-01): MuJoCo on the CAD plate seated almost nothing at 3 degrees. Find the Isaac yaw boundary at 0.5 and 1 degree
# (beyond about 1.3 degrees the 90 mm box overruns the 1 mm bin-extent band, a judging limit).
for _name, _yaw in (('w05', .5), ('w10', 1.)):
    for _base in ('g315', 'r290-g315'):
        FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-'+_name+'-'+_base] = dict(
            FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-'+_base], release_yaw_rad=math.radians(_yaw))
# Step 4c (2026-11-02): fill the relief-foot boundary in 0.1 mm steps on both sides, several seeds (Isaac band about +-0.7 mm in Step 4b).
for _name, _offset in (('y060', .0006), ('y070', .0007), ('y-060', -.0006), ('y-070', -.0007)):
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-'+_name+'-r290-g315'] = dict(
        FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-r290-g315'], release_offset_m=[0., _offset])
# Cell survey 2026-11-03 (docs/validation/omx-cell-survey-2026-11-03): the CAD arm bases and belt against the measured ones,
# candidates side by side (D-947 2). arm_b (index 1) by FK of its own joint states; arm_a by its base plate centre (no FK, yaw
# kept). The belt by D435 depth at the belt end: 28 mm below the CAD face.
SURVEYED_BASES = dict(arm_bases_m=[[.116, -.164, .072], [.104, .153, .072]], arm_base_yaws_rad=[math.pi/2, math.radians(-94.3)])
# From these bases arm_a cannot reach the shared leveling spot past the bow (0.287 m), so each arm levels on its own spot:
# the user's slot in front of each arm (plan 2026-10-31: about 170 mm from the base away from the belt, off the plate).
# arm_a's straight path from home to its spot passes 35 mm from its own base axis (a wrist singularity in the planner), so it
# goes over the empty bow-side cells of the plate; arm_b goes straight.
SURVEYED_BASES.update(leveling_centers_m=[[.116-.17, -.164, .072], [.104-.17, .153, .072]], leveling_via_m=None,
                      leveling_vias_m=[[-.004, -.084, .212], None], leveling_carry_height_m=.212)
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases'] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'],
                                                                        planning_scene='surveyed-bases-20261103', **SURVEYED_BASES)
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed'] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases'],
                                                                  planning_scene='surveyed-cell-20261103', belt_drop_m=.028)
# D-969 step 1: the 9/9 CAD ship case with the two-arm demonstration recording on (real top and side views, both arms' state
# and commanded targets at 10 Hz). Same geometry and teacher as the plain case; only the recording differs.
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-demo'] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'], demo_recording=True)
# D-969 step 5 smoke: the 20-step CPU ACT checkpoint (seed 42 demos) drives both arms for 30 s per container, to prove the
# closed loop runs end to end; it is not expected to stack. Checkpoint: ~/rosy-learning/policies/<sha256> on the model PC.
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-policy-smoke'] = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'], policy=dict(
    env='act-env-20261103', model_sha256='f98e17296e82e88eb08cfb488f904b9a39bad005ef9387ef5ccab633abe60233',
    image_size=[320, 240], ticks_per_action=24, max_actions=150))
# D-969 data production: the surveyed bases placed 9/9 (run 2b27f66c, 2026-11-03), so demonstrations are recorded on the
# geometry of the real cell.
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases-demo'] = dict(
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases'], demo_recording=True)
# D-969 data production default (2026-11-03): the surveyed bases placed 9/9 (run 2b27f66c), so demonstrations come from the
# geometry the real cell has, with recording on and no debug aids.
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases-demo'] = dict(
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases'], demo_recording=True)
# Team end part (2026-11-04): the same demonstrations with a wrist camera per arm on the printed wrist holder (b16-u16-span-D r06, 2026-11-07),
# so an ACT policy trained here sees the wrist view the real arms will have. Image orientation is ASSUMED (wrist_camera_pose).
FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases-wrist-demo'] = dict(
    FIXTURE_OVERRIDES['nominal-palletizing-v21-ship-surveyed-bases-demo'], wrist_camera=dict(WRIST_CAMERA_B))
# D-956 in Isaac (2026-11-04): MuJoCo's whole-stack sweep says a 2 mm release plus a seat check and one corrected re-place keeps
# every stack up to 0.8 mm release error (24/24, plain 2/24). Same deliberate offsets across the channel, with and without it.
SEAT_REPLACE = dict(height_m=.0005, tilt_rad=math.radians(.5), residual_m=.0001)  # D-956 limits; residual as in MuJoCo
for _name, _offset in (('y060', .0006), ('y080', .0008)):
    _base = dict(FIXTURE_OVERRIDES['nominal-palletizing-v21-ship'], release_gap_m=.0315, stack_release_clearance_m=.002,
                 release_offset_m=[0., _offset])
    FIXTURE_OVERRIDES[f'nominal-palletizing-v21-ship-{_name}-c2-g315'] = _base
    FIXTURE_OVERRIDES[f'nominal-palletizing-v21-ship-{_name}-c2-seat-g315'] = dict(_base, seat_replace=dict(SEAT_REPLACE))
