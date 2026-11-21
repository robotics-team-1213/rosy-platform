"""RSL-RL PPO environment and bounded training/evaluation rollout for OMX-F stacking."""
import hashlib
import json
import math

from stacking_fixture import BELT_TOP, DT, UNIT, advance_joint, placed, target


def record_evaluation_step(rows, step):
    """Summarize sequential cargo progress without retaining the entire rollout."""
    item = rows.setdefault(step["id"], dict(arm=step["arm"], samples=0,
                           min_tcp_distance_m=step["tcp_distance_m"], max_rise_m=0.,
                           max_opposing_contact_n=0., lifted=False, seated=False))
    item["samples"] += 1
    item["min_tcp_distance_m"] = min(item["min_tcp_distance_m"], step["tcp_distance_m"])
    item["max_rise_m"] = max(item["max_rise_m"], step["rise_m"])
    item["max_opposing_contact_n"] = max(item["max_opposing_contact_n"], min(step["finger_forces_n"]))
    item["lifted"] |= step["lifted"]
    item["seated"] |= step["seated"]
    item["last_position_m"] = step["position_m"]
    item["last_goal_distance_m"] = step["goal_distance_m"]
    item["terminal"] = step["terminal"]


def record_replay_phases(phases, index, *, lifted, at_target, seated):
    """Record the first sample for each ordered, independently observed phase."""
    if "unsupported_lift" not in phases:
        if lifted:
            phases["unsupported_lift"] = index
    elif "held_at_target" not in phases:
        if at_target:
            phases["held_at_target"] = index
    elif seated:
        phases.setdefault("settled_on_support", index)


def load_first_pick_replay(path, fixture, profile, item):
    """Check a bounded teacher trace before using it in the simulation scene."""
    import numpy as np

    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Replay input exceeds 1 MiB")
    value = json.loads(raw)
    joints = [f"joint{i}" for i in range(1, 6)] + ["gripper_joint_1"]
    dt = DT * fixture["control_decimation"]
    if (value.get("schema") != "omx.sim-replay-targets/1" or value.get("scenario") != fixture["case"]
            or item["arm"] != 1 or value.get("arm") != "arm_b"
            or value.get("target") != "ship-h1r1-l0" or value.get("joints") != joints
            or value.get("control_hz") != round(1 / dt)):
        raise ValueError("Replay does not match the CAD194 first pick")
    samples = np.asarray(value["target_rad"], dtype=float)
    if (samples.ndim != 2 or samples.shape[1] != 6 or not 2 <= len(samples) <= 6000
            or not np.isfinite(samples).all()
            or not np.allclose(samples[0], [*fixture["home_joints_rad"][1], 1.], rtol=0., atol=1e-6)):
        raise ValueError("Invalid replay samples or first pose")
    limits = [profile["joints"][name] for name in joints[:5]] + [profile["gripper"]]
    pos = np.array([limit["position"] for limit in limits])
    velocity = np.diff(samples, axis=0) / dt
    acceleration = np.diff(np.vstack([np.zeros(6), velocity, np.zeros(6)]), axis=0) / dt
    if (np.any(samples < pos[:, 0]) or np.any(samples > pos[:, 1])
            or np.any(np.max(np.abs(velocity), axis=0) > np.array([x["velocity"] for x in limits]) + 1e-9)
            or np.any(np.max(np.abs(acceleration), axis=0) > np.array([x["acceleration"] for x in limits]) + 1e-9)):
        raise ValueError("Replay samples exceed simulation profile limits")
    return samples, hashlib.sha256(raw).hexdigest()


def run_ppo_stacking(args, world, stage, robots, links, joint_indices, fingers, cargo, contacts,
                     plan, profile, capture, tcp_position, initial, *, mapped, fixture):
    """Run the StackingEnv RSL-RL PPO training and deterministic evaluation episode."""
    import numpy as np
    import torch
    from tensordict import TensorDict
    from pxr import UsdGeom
    from isaacsim.core.utils.types import ArticulationAction
    from rsl_rl.runners import OnPolicyRunner

    if mapped:
        from mapped_stack_fixture import free_lift, stable_box
        from mapped_stack_task import apply_servo
    replay = getattr(args, "first_pick_replay", None)
    if replay:
        samples, replay_sha = load_first_pick_replay(replay, fixture, profile, plan[0])

    def goal(item):
        return item['target'] if mapped else target(item)

    def accepted(index, sample):
        if not mapped:
            return placed(plan[index], **sample)
        for i in range(2):
            tcp = tcp_position(i)
            if np.linalg.norm(tcp-np.array(sample['position'])) < .04:
                return False
        return sample['lifted'] and stable_box(sample['body'], index,
            cube='pickup_center_m' in fixture, fixture=fixture)

    class StackingEnv:
        # shortcut: one CPU-facing SDK world, use Isaac Lab vector scenes when measured rollout throughput is limiting.
        num_envs, num_actions, max_episode_length, device = 1, 12, fixture.get('max_episode_steps', 600), 'cuda:0'
        cfg = dict(fixture)

        def __init__(self):
            self.episode_length_buf = torch.zeros(1, dtype=torch.long, device=self.device)
            self.transitions = self.completed = self.episodes = 0
            self.rng = np.random.default_rng(args.seed)
            self.belt_start = self.belt_observed = None
            self.auto_reset = True
            self.reset()

        def reset(self, seed=None):
            if seed is not None:
                self.rng = np.random.default_rng(seed)
            self.index, self.lifted, self.settle = 0, False, 0
            self.episode_length_buf.zero_()
            self.targets, self.target_velocities = [], []
            for i, box in enumerate(cargo):
                box.set_world_pose(np.array([-.45, .4+i*.065, .016] if mapped else [.7, -.5+i*.065, .015]), np.array([1., 0., 0., 0.]))
                box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
                if mapped:
                    UsdGeom.Imageable(box.prim).MakeInvisible()
            for i, robot in enumerate(robots):
                state = np.zeros(robot.num_dof)
                state[joint_indices[i]] = initial['homes'][i] if mapped else [0., -.4, .7, 1.27, 0.]
                state[fingers[i]] = [1., -1.]
                robot.set_joint_positions(state)
                robot.set_joint_velocities(np.zeros(robot.num_dof))
                robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=state))
                self.targets.append(state.copy())
                self.target_velocities.append(np.zeros(robot.num_dof))
            self.activate()
            for _ in range(12):
                if mapped:
                    for i, robot in enumerate(robots):
                        apply_servo(robot, self.targets[i], joint_indices[i], fingers[i])
                for _ in range(fixture.get('physics_substeps', 1)):
                    world.step(render=False, update_fabric=True)
            return self.get_observations()

        def activate(self):
            jitter_xy = fixture.get('infeed_jitter_xy_m', [.003, .003])
            jitter = self.rng.uniform(-1., 1., 2)*jitter_xy
            yaw = self.rng.uniform(-fixture.get('infeed_yaw_jitter_rad', .03),
                                   fixture.get('infeed_yaw_jitter_rad', .03))
            if replay:
                jitter, yaw = (0., 0.), 0.
            source = fixture.get('pickup_center_m', [(.16 if mapped else .20), -.09, BELT_TOP+.016])
            pose = [source[0]+jitter[0], source[1]+jitter[1], source[2]]
            self.source_z = pose[2]
            cargo[self.index].set_world_pose(np.array(pose),
                np.array([math.cos(yaw/2), 0., 0., math.sin(yaw/2)]))
            cargo[self.index].set_linear_velocity(np.zeros(3))
            cargo[self.index].set_angular_velocity(np.zeros(3))
            if mapped:
                UsdGeom.Imageable(cargo[self.index].prim).MakeVisible()
            self.lifted, self.settle = False, 0

        def measured(self, index):
            position, orientation = cargo[index].get_world_pose()
            vectors = np.asarray(contacts[index].get_contact_force_matrix(dt=fixture.get('physics_dt_s', DT)))[0]
            force = np.linalg.norm(vectors[:4], axis=-1)
            speed = max(float(np.linalg.norm(cargo[index].get_linear_velocity())),
                        UNIT*float(np.linalg.norm(cargo[index].get_angular_velocity())))
            sample = dict(position=position.tolist(), orientation=orientation.tolist(), speed=speed,
                finger_force=float(force.sum()), support_force=max(0., float(vectors[4:, 2].sum())),
                lifted=self.lifted)
            if mapped:
                sample['body'] = dict(position=position.tolist(), orientation=orientation.tolist(),
                    velocity=cargo[index].get_linear_velocity().tolist(), angular_velocity=cargo[index].get_angular_velocity().tolist(),
                    forces=vectors.tolist(), net_force=np.asarray(contacts[index].get_net_contact_forces(dt=fixture.get('physics_dt_s', DT)))[0].tolist())
            return position, sample, force

        def get_observations(self):
            values = []
            for robot in robots:
                values.extend(robot.get_joint_positions().tolist())
                values.extend(robot.get_joint_velocities().tolist())
            p, q = cargo[self.index].get_world_pose()
            values.extend(p); values.extend(q)
            values.extend(cargo[self.index].get_linear_velocity())
            values.extend(goal(plan[self.index]))
            values.extend([self.index/len(plan), float(self.lifted), plan[self.index]['cells']/3,
                           float(plan[self.index]['arm'])])
            obs = torch.tensor([values], dtype=torch.float32, device=self.device)
            if not torch.isfinite(obs).all():
                raise RuntimeError('Nonfinite stacking observation '+repr(dict(
                    step=self.transitions, cargo=self.index, values=values)))
            return TensorDict({'policy': obs}, batch_size=[1])

        def step(self, actions):
            action = actions.detach().clamp(-1., 1.).cpu().numpy()[0]
            if not np.isfinite(action).all():
                raise ValueError('Finite policy actions required')
            active = plan[self.index]['arm']
            braking = any(np.max(np.abs(self.target_velocities[i])) > 1e-8
                          for i in range(2) if i != active)
            for i, robot in enumerate(robots):
                moving = i == active and not braking
                state, speed = self.targets[i], self.target_velocities[i]
                control_dt = DT*fixture['control_decimation']
                for n, idx in enumerate(joint_indices[i]):
                    limit = profile['joints']['joint'+str(n+1)]
                    state[idx], speed[idx] = advance_joint(state[idx], speed[idx],
                        action[i*6+n]*limit['velocity'] if moving else 0., limit, control_dt)
                grip = profile['gripper']
                idx = fingers[i][0]
                grip_goal = (grip['position'][0]+(grip['position'][1]-grip['position'][0])*(action[i*6+5]+1)/2
                        if moving else state[idx])
                opening, speed[idx] = advance_joint(state[idx], speed[idx], (grip_goal-state[idx])/control_dt, grip, control_dt)
                state[fingers[i]] = [opening, -opening]
                if not mapped:
                    robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=state))
            for _ in range(fixture['control_decimation']):
                if mapped:
                    for i, robot in enumerate(robots):
                        apply_servo(robot, self.targets[i], joint_indices[i], fingers[i])
                for _ in range(fixture.get('physics_substeps', 1)):
                    world.step(render=False, update_fabric=True)
            self.transitions += 1
            self.episode_length_buf += 1
            p, sample, force = self.measured(self.index)
            self.lifted |= (free_lift(sample['body'], active, self.source_z) if mapped else
                bool(p[2] > BELT_TOP+.015+.02 and np.all(force[2*active:2*active+2] > .005)))
            sample['lifted'] = self.lifted
            good = accepted(self.index, sample)
            if mapped:
                tcp = tcp_position(active)
            else:
                tcp = np.array(UsdGeom.XformCache().GetLocalToWorldTransform(
                    stage.GetPrimAtPath(links[active]['end_effector_link'])).ExtractTranslation())
            reach = float(np.linalg.norm(tcp-p))
            distance = float(np.linalg.norm(p-np.array(goal(plan[self.index]))))
            rise = float(p[2]-self.source_z)
            reward = math.exp(-20*reach)+float(self.lifted)*(2+2*math.exp(-25*distance))-.01*float(np.square(action).sum())
            done = bool(p[2] < -.01 or np.linalg.norm(p[:2]) > .6)
            for i in range(self.index):
                _, previous, _ = self.measured(i)
                previous['lifted'] = True
                # New loads may increase support forces; any displaced earlier cargo invalidates this stack.
                if mapped:
                    done |= np.max(np.abs(np.array(previous['position'])-np.array(goal(plan[i])))) > .01
                    good &= accepted(i, previous)
                else:
                    done |= not accepted(i, previous)
            self.settle = self.settle+1 if good else 0
            settle_steps = fixture['settle_steps']//fixture['control_decimation'] if mapped else fixture['settle_steps']
            item = plan[self.index]
            success = not done and self.settle >= settle_steps
            full_stack = success and self.index == len(plan)-1
            if success:
                reward += 20
                self.completed += 1
                if self.index == len(plan)-1:
                    done = True
                else:
                    self.index += 1
                    self.activate()
            timeout = bool(self.episode_length_buf[0] >= self.max_episode_length)
            info = dict(time_outs=torch.tensor([timeout and not done], device=self.device),
                        log={'Stack/placed': float(self.completed)}, stack_success=full_stack)
            if fixture.get('r08_scene') and not self.auto_reset:
                info['evaluation_step'] = dict(
                    id=item['id'], arm=int(active), tcp_distance_m=reach, rise_m=rise,
                    finger_forces_n=force[2*active:2*active+2].tolist(), lifted=sample['lifted'],
                    seated=bool(success), position_m=sample['position'], goal_distance_m=distance,
                    terminal=('stack_complete' if full_stack else 'invalid_cargo_pose' if done else 'timeout' if timeout else None))
            done |= timeout
            if done:
                self.episodes += 1
                if self.auto_reset:
                    self.reset()
            return self.get_observations(), torch.tensor([reward], device=self.device), torch.tensor([done], device=self.device), info

    env = StackingEnv()
    if replay:
        from mapped_stack_fixture_helpers import half_extent, unsupported_hold

        active, summaries = plan[0]["arm"], {}
        item = plan[0]
        destination = np.array(goal(item))
        phases = {}
        current = env.targets[active]
        settle_steps = fixture["settle_steps"] // fixture["control_decimation"]
        for index, command in enumerate(samples):
            current[joint_indices[active]] = command[:5]
            current[fingers[active]] = [command[5], -command[5]]
            for _ in range(fixture["control_decimation"]):
                for arm, robot in enumerate(robots):
                    apply_servo(robot, env.targets[arm], joint_indices[arm], fingers[arm])
                for _ in range(fixture["physics_substeps"]):
                    world.step(render=False, update_fabric=True)
            position, row, forces = env.measured(0)
            body = row["body"]
            lifted = free_lift(body, active, env.source_z)
            env.lifted |= lifted
            row["lifted"] = env.lifted
            env.settle = env.settle + 1 if accepted(0, row) else 0
            seated = env.settle >= settle_steps
            at_target = unsupported_hold(body, active) and all(
                abs(position[axis] - destination[axis]) <= half_extent(body, item["size"], axis)
                for axis in (0, 1)
            )
            record_replay_phases(phases, index, lifted=lifted, at_target=at_target, seated=seated)
            record_evaluation_step(summaries, dict(
                id=item["id"], arm=active, tcp_distance_m=float(np.linalg.norm(tcp_position(active)-position)),
                rise_m=float(position[2]-env.source_z), finger_forces_n=forces[2*active:2*active+2].tolist(),
                lifted=env.lifted, seated=seated, position_m=row["position"],
                goal_distance_m=float(np.linalg.norm(position-destination)),
                terminal="replay_finished" if index == len(samples)-1 else None))
        capture("first-pick-final.png")
        settled = env.settle >= settle_steps
        return dict(schema="rosy.omx-first-pick-replay/1", seed=args.seed, fixture=fixture,
                    target_sha256=replay_sha, samples=len(samples), attachment_aid=False,
                    settled_on_target=settled, observed_phases=phases,
                    task_success=settled and "settled_on_support" in phases, progress=summaries,
                    image="first-pick-final.png")

    # Observe uncommanded cargo transport on the belt before any policy is applied.
    if 'belt_probe_start_m' in fixture:
        cargo[0].set_world_pose(np.array(fixture['belt_probe_start_m']), np.array([1., 0., 0., 0.]))
        cargo[0].set_linear_velocity(np.zeros(3))
        cargo[0].set_angular_velocity(np.zeros(3))
    start = cargo[0].get_world_pose()[0].copy()
    for _ in range(120):
        for _ in range(fixture.get('physics_substeps', 1)):
            world.step(render=False, update_fabric=True)
    belt_motion = (cargo[0].get_world_pose()[0]-start).tolist()
    capture('stacking-initial.png')
    print('OMX_STACKING_SCENE_READY', json.dumps(dict(arms=2, cargo=len(plan),
        bin_size_m=fixture['bin_size_m'], belt_displacement_m=belt_motion)), flush=True)
    env.reset()
    network = dict(class_name='MLPModel', hidden_dims=[64, 64], activation='elu', obs_normalization=True)
    cfg = dict(seed=args.seed, device=env.device, num_steps_per_env=32, save_interval=32,
        obs_groups={'actor': ['policy'], 'critic': ['policy']}, logger='tensorboard',
        actor=dict(network, distribution_cfg={'class_name': 'GaussianDistribution', 'init_std': .4}),
        critic=dict(network, distribution_cfg=None), algorithm=dict(class_name='PPO',
        num_learning_epochs=4, num_mini_batches=4, learning_rate=.0003, schedule='fixed', gamma=.99,
        lam=.95, entropy_coef=.005, desired_kl=.01, max_grad_norm=1., value_loss_coef=1.,
        use_clipped_value_loss=True, clip_param=.2))
    runner = OnPolicyRunner(env, cfg, log_dir=str(args.report.parent/'training'), device=env.device)
    before = torch.nn.utils.parameters_to_vector(runner.alg.get_policy().parameters()).detach().clone()
    runner.learn(num_learning_iterations=32, init_at_random_ep_len=False)
    after = torch.nn.utils.parameters_to_vector(runner.alg.get_policy().parameters()).detach()
    delta = float(torch.linalg.vector_norm(after-before))
    checkpoint = args.report.parent/'stacking-policy.pt'
    runner.save(str(checkpoint))
    trained_transitions = env.transitions
    policy = runner.get_inference_policy(device=env.device)
    env.auto_reset = False
    obs = env.reset(seed=args.seed+fixture['evaluation_seed_offset'])
    evaluation_successes = 0
    evaluation_progress = {}
    for _ in range(env.max_episode_length):
        with torch.inference_mode():
            action = policy(obs)
        obs, _, done, info = env.step(action)
        evaluation_successes += int(info['stack_success'])
        if 'evaluation_step' in info:
            record_evaluation_step(evaluation_progress, info['evaluation_step'])
        if bool(done[0]):
            break
    capture('stacking-evaluation.png')
    stage.GetRootLayer().Export(str(args.report.parent/'stacking-scene.usda'))
    report = dict(schema='rosy.omx-stacking-rl/1', fixture=fixture, seed=args.seed,
        updates=32, transitions=trained_transitions, parameter_delta=delta,
        training_verified=bool(math.isfinite(delta) and delta > 0), task_success=evaluation_successes > 0,
        evaluation_seed=args.seed+fixture['evaluation_seed_offset'], evaluation_episodes=1,
        evaluation_successes=evaluation_successes, evaluation_steps=env.transitions-trained_transitions,
        belt_displacement_m=belt_motion, articulations=[str(r.prim_path) for r in robots],
        joints=[list(r.dof_names) for r in robots], attachment_aid=False,
        checkpoint=dict(name=checkpoint.name, bytes=checkpoint.stat().st_size,
                        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest()),
        images=['stacking-initial.png', 'stacking-evaluation.png'])
    if fixture.get('r08_scene'):
        report['evaluation_progress'] = evaluation_progress
    return report
