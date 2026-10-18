"""Optional LeRobot 0.4.4 Robot: observation and actions go exclusively through CORE."""
import base64
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from lerobot.robots import Robot, RobotConfig

from rosy.integrations.robots.omx.core_arm_client import CoreArmClient


@RobotConfig.register_subclass('rosy_omx')
@dataclass(kw_only=True)
class RosyOmxConfig(RobotConfig):
    url: str
    token_file: str
    policy_revision: str
    joint_names: tuple[str, ...]
    camera_height: int
    camera_width: int
    camera_name: str = 'front'

    def __post_init__(self):
        if (not self.joint_names or len(set(self.joint_names)) != len(self.joint_names)
                or any(not name.strip() for name in self.joint_names) or not self.camera_name.strip()
                or any(type(n) is not int or not 1 <= n <= 4096
                       for n in (self.camera_height, self.camera_width))):
            raise ValueError('distinct joint names and positive RGB dimensions required')


class RosyOmx(Robot):
    config_class = RosyOmxConfig
    name = 'rosy_omx'

    def __init__(self, config):
        super().__init__(config)
        self.config, self._client = config, None

    @property
    def action_features(self):
        return {name + '.pos': float for name in self.config.joint_names}

    @property
    def observation_features(self):
        return {**self.action_features,
                self.config.camera_name: (self.config.camera_height, self.config.camera_width, 3)}

    @property
    def is_connected(self):
        return self._client is not None and self._client.is_connected

    @property
    def is_calibrated(self):
        return self.is_connected  # Calibration is checked by the installed CORE/owner session.

    def calibrate(self):
        raise RuntimeError('commission and calibrate the OMX through its owner before connecting')

    def configure(self):
        pass  # CORE owns device configuration; this client cannot change it.

    def connect(self, calibrate=True):
        if self.is_connected:
            raise RuntimeError('CORE arm is already connected')
        client = CoreArmClient(self.config.url,
            token=Path(self.config.token_file).read_text(encoding='utf-8').strip(),
            policy_revision=self.config.policy_revision)
        client.connect()
        expected = dict(name=self.config.camera_name,
                        shape=[3, self.config.camera_height, self.config.camera_width])
        if (client.info['joint_names'] != list(self.config.joint_names) or client.info['camera'] != expected):
            raise ValueError('CORE joint order or RGB camera differs from LeRobot config')
        self._client = client

    def get_observation(self):
        if not self.is_connected:
            raise RuntimeError('connect to CORE before reading an observation')
        source = self._client.get_observation()
        try:
            raw = base64.b64decode(source['camera']['rgb_base64'], validate=True)
            image = np.frombuffer(raw, dtype=np.uint8).reshape(
                self.config.camera_height, self.config.camera_width, 3).copy()
            return {**{name + '.pos': source['positions'][name] for name in self.config.joint_names},
                    self.config.camera_name: image}
        except Exception:
            self._client.disconnect()
            raise

    def send_action(self, action):
        if not self.is_connected or set(action) != set(self.action_features):
            raise ValueError('connected CORE and exact installed joint action features required')
        positions = {name: float(action[name + '.pos']) for name in self.config.joint_names}
        sent = self._client.send_action(positions)
        return {name + '.pos': value for name, value in sent.items()}

    def disconnect(self):
        if self._client is not None:
            self._client.disconnect()


def record():
    """Register this Robot before invoking the unchanged official recorder CLI."""
    from lerobot.scripts.lerobot_record import main
    main()
