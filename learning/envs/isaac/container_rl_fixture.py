"""Bounded PPO settings over the current CAD container contact scene."""

from mapped_stack_fixture import container_fixture


def fixture(*, layers, case):
    value = container_fixture(layers=layers, case=case)
    return dict(value, revision=value['revision']+'-ppo-v1',
                controller='RSL_RL_PPO_DIRECT_JOINT_VELOCITY',
                control_decimation=4, max_episode_steps=1800*layers,
                iterations=32, steps_per_update=32, num_envs=1,
                evaluation_seed_offset=10000)
