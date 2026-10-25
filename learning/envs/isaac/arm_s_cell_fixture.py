"""Arm S cell in Isaac (D-872): the real cell's top-down chunk frames replayed against tray, belt and the
Pinky frame beside the tray, with the 2026-10-25 failures as scenarios. Isaac-free: geometry, scenarios and
the judgement read only measured samples.

Heights come from the real grasps, not the camera: the arm grasped the 40 mm box with the tool centre at
z 0.060 m (15 mm below its top), so the tray top is at 0.035 m; the belt place at 0.064 m puts the belt top at
0.039 m. The Pinky frame is a block 25 mm above the tray on its +y side, where a calibration point put the
box's edge on 2026-10-25. Coordinates are the arm's own (link0 = world), from forward kinematics of those
grasps: ARM_FK_FROM_REAL_GRASPS_NOT_CAMERA_REGISTERED.
"""
import math

BOX = .040
# The box sits square to the jaws at the site's yaw (grasp-plan pick yaw_deg), as on the real tray. Spawned at
# 0 deg instead, the jaws closed across it diagonally, it twisted into line while lifting and its corner hit
# the frame (first Isaac run, 2026-10-25). Scenario yaws are relative to this.
BOX_YAW_DEG = -67.8
TRAY = dict(center=(.072, .106), size=(.06, .06), top=.035)
BELT = dict(center=(.150, .000), size=(.08, .14), top=.039)
# the Pinky body beside the tray (+y). A box square to the jaws reaches 26 mm toward it; at 30 mm from the
# tray centre the box rubbed it on every lift (second Isaac runs), so it starts 45 mm out: 19 mm clear.
FRAME = dict(center=(.072, .168), size=(.08, .034), top=.060)
FIXTURE = dict(revision='arm-s-cell-v1', coordinate_scope='ARM_FK_FROM_REAL_GRASPS_NOT_CAMERA_REGISTERED',
               box_size_m=BOX, box_mass_kg=.03, tray=TRAY, belt=BELT, pinky_frame=FRAME,
               physics_dt_s=1 / 120, frame_fps=30, friction=1., restitution=0.,
               gripper_open_rad=1., gripper_closed_rad=-.12, finger_max_effort_nm=.2,
               arm_drive_stiffness=5000., arm_drive_damping=100., arm_max_effort_nm=30.,
               # shortcut: the two fingers are independent effort-capped drives; the real gripper is one motor and
               # a linkage. They push equally wherever the box sits, so it slides ~16 mm sideways in the jaws
               # while carried (nominal sets down 15.6 mm off). A controller mirror and a PhysX mimic joint both
               # squeezed the box out (2026-10-25); upgrade when a coupled gripper holds the box in Isaac.
               finger_coupling='NONE_INDEPENDENT_DRIVES',
               controller='ARM_S_CHUNK_FRAMES_NOT_LEARNED_POLICY', attachment_aid=False)
# scenario -> (box start on the tray: dx, dy, yaw deg), place target on the belt or a tray point
SCENARIOS = {
    'nominal': dict(box=(0., 0., 0.), place='belt', expect='placed'),
    'overhang': dict(box=(0., 0., 0.), place=(.072, .135), expect='frame_contact'),  # the box's edge over the frame
    'wrong-yaw': dict(box=(0., 0., 20.), place='belt', expect='not_held'),  # jaws at the site yaw on a turned box
}
# a body joint lagging its command by this much is the runner's soft contact (1.5 units of at most 1.8 deg)
SOFT_CONTACT_RAD = 1.5 * math.radians(1.8)


def box_start(scenario):
    """(x, y, z) of the box centre and its yaw in degrees, square to the jaws unless the scenario turns it."""
    dx, dy, yaw = SCENARIOS[scenario]['box']
    return (TRAY['center'][0] + dx, TRAY['center'][1] + dy, TRAY['top'] + BOX / 2), BOX_YAW_DEG + yaw


def place_point(scenario):
    place = SCENARIOS[scenario]['place']
    return (BELT['center'][0], BELT['center'][1], BELT['top']) if place == 'belt' else (*place, TRAY['top'])


def evaluate(samples, scenario):
    """From measured samples only: where the box ended, whether the jaws held it while lifted, whether
    anything touched the Pinky frame, and the largest arm following error and when it first passed the
    runner's soft-contact bound. `result` compares that with the scenario's expectation."""
    if not samples:
        return dict(result='no_samples', matches_expectation=False)
    place = place_point(scenario)
    final = samples[-1]['box_position']
    lifted = [s for s in samples if s['box_position'][2] > TRAY['top'] + BOX / 2 + .02]
    frame_contact = max((s['frame_contact_n'] for s in samples), default=0.) > .05
    lag = [s['joint_error_rad'] for s in samples]
    soft = next((s['tick'] for s in samples if s['joint_error_rad'] > SOFT_CONTACT_RAD), None)
    placed = (math.hypot(final[0] - place[0], final[1] - place[1]) <= .015
              and abs(final[2] - place[2] - BOX / 2) <= .006 and not frame_contact)
    outcome = 'frame_contact' if frame_contact else 'placed' if placed else 'held_not_placed' if lifted else 'not_held'
    return dict(result=outcome, matches_expectation=outcome == SCENARIOS[scenario]['expect'],
                final_box_m=[round(v, 4) for v in final], max_joint_error_rad=round(max(lag), 4),
                first_soft_contact_tick=soft, frame_contact=frame_contact, lifted_samples=len(lifted))
