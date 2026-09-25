import json
import os
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from ament_index_python.packages import get_package_share_directory
from PIL import Image, ImageSequence
from std_msgs.msg import String

from interfaces.srv import Emotion

from .info_screen import render as render_info
from .rosy_lcd import LCD

# core가 latch로 발행하므로 늦게 떠도 현재 모드를 즉시 받는다 (PWR-003).
_LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)

_VALID_MODES = ("active", "idle", "standby")


class RosyEmotion(Node):
    def __init__(self):
        super().__init__('emotion')

        self.declare_parameter('load_frame_skip', 2)
        self.declare_parameter('play_frame_skip', 1)
        # PWR-003 모드별 백라이트 듀티(%). standby=0이면 백라이트가 완전히 꺼진다.
        self.declare_parameter('backlight_active', 100)
        self.declare_parameter('backlight_idle', 30)
        self.declare_parameter('backlight_standby', 0)

        self.load_frame_skip = self.get_parameter('load_frame_skip').get_parameter_value().integer_value
        self.play_frame_skip = self.get_parameter('play_frame_skip').get_parameter_value().integer_value

        self.get_logger().info(f"load_frame_skip: {self.load_frame_skip} frame")
        self.get_logger().info(f"play_frame_skip: {self.play_frame_skip} frame")

        self.emotion_path = os.path.join(get_package_share_directory('emotion'), 'emotion')
        self.emotion_service = self.create_service(Emotion, 'set_emotion', self.set_emotion_callback)
        self.lcd = LCD()

        self.gif_frames = []
        self.current_frame_index = 0
        self.gif_lock = threading.Lock()

        self.emotion_cache = {}
        self._preload_gifs()

        # PWR-003 절전/정보 화면 상태
        self.power_mode = 'active'
        self.display_sleeping = False
        self.info_image = None
        self.info_until = 0.0
        self._shown_info = None

        self.create_subscription(String, 'power/mode', self.power_mode_callback, _LATCHED)
        self.create_subscription(String, 'display/info', self.display_info_callback, 10)

        self.animation_timer = self.create_timer(0.1, self.timer_callback)

        self.get_logger().info("Rosy's emotion server is ready!! All GIFs pre-loaded.")

        with self.gif_lock:
            self.gif_frames = self.emotion_cache.get("happy", [])

    def _preload_gifs(self):
        self.get_logger().info("Pre-loading all emotion GIFs into memory...")
        try:
            gif_files = [f for f in os.listdir(self.emotion_path) if f.endswith('.gif')]
            for gif_file in gif_files:
                emotion_name = os.path.splitext(gif_file)[0]
                file_path = os.path.join(self.emotion_path, gif_file)

                img = Image.open(file_path)
                frames = []
                for i, frame in enumerate(ImageSequence.Iterator(img)):
                    if i % self.load_frame_skip == 0:
                        frames.append(frame.copy().convert("RGB"))

                self.emotion_cache[emotion_name] = frames
                self.get_logger().info(f"  - Cached '{emotion_name}' ({len(frames)} frames)")
        except Exception as e:
            self.get_logger().error(f"Failed during GIF pre-loading: {e}")

    def set_emotion_callback(self, request, response):
        emo = request.emotion
        self.get_logger().info(f"Request to set emotion to '{emo}'")

        if emo in self.emotion_cache:
            with self.gif_lock:
                self.gif_frames = self.emotion_cache[emo]
                self.current_frame_index = 0
            response.response = f"Emotion set to {emo}"
        else:
            response.response = "Wrong command or emotion not cached"
            self.get_logger().warn(f"Emotion '{emo}' not found in cache.")

        return response

    # --- PWR-003 절전/정보 화면 ---------------------------------------------

    def _lcd(self, action, *args):
        """LCD는 표시 장치일 뿐이다 — 실패해도 노드를 죽이지 않는다."""
        try:
            getattr(self.lcd, action)(*args)
        except Exception as e:
            self.get_logger().warn(f"LCD {action} failed: {e}")

    def _backlight_for(self, mode):
        return self.get_parameter(f'backlight_{mode}').get_parameter_value().integer_value

    def _wake_display(self):
        if self.display_sleeping:
            self._lcd('wake')
            self.display_sleeping = False

    def _apply_power_mode(self, mode):
        if mode == 'standby':
            self._lcd('set_backlight', self._backlight_for('standby'))
            if not self.display_sleeping:
                self._lcd('sleep')
                self.display_sleeping = True
            return
        self._wake_display()
        self._lcd('set_backlight', self._backlight_for(mode))

    def power_mode_callback(self, msg):
        mode = msg.data.strip().lower()
        if mode not in _VALID_MODES:
            self.get_logger().warn(f"Ignoring unknown power mode '{msg.data}'")
            return
        if mode == self.power_mode:
            return

        self.power_mode = mode
        self.get_logger().info(f"power mode -> {mode}")
        self._apply_power_mode(mode)

    def display_info_callback(self, msg):
        try:
            payload = json.loads(msg.data)
        except (ValueError, TypeError) as e:
            self.get_logger().warn(f"Ignoring malformed display/info: {e}")
            return
        if not isinstance(payload, dict):
            self.get_logger().warn("Ignoring display/info: payload is not an object")
            return

        hold_s = float(payload.get('hold_s') or 15.0)
        size = self._frame_size()
        try:
            image = render_info(payload, size=size)
        except Exception as e:
            self.get_logger().error(f"Failed to render info screen: {e}")
            return

        with self.gif_lock:
            self.info_image = image
            self.info_until = time.monotonic() + hold_s

        # power/mode가 아직 안 왔더라도 정보 화면은 반드시 보여야 한다.
        self._wake_display()
        self._lcd('set_backlight', self._backlight_for('active'))

    def _frame_size(self):
        with self.gif_lock:
            frames = self.gif_frames
        return frames[0].size if frames else (self.lcd.h, self.lcd.w)

    def timer_callback(self):
        now = time.monotonic()

        with self.gif_lock:
            info_image = self.info_image
            info_until = self.info_until

        if info_image is not None:
            if now < info_until:
                if self._shown_info is not info_image:
                    self._lcd('img_show', info_image)
                    self._shown_info = info_image
                return
            # 만료 — 감정 애니메이션으로 복귀
            with self.gif_lock:
                self.info_image = None
            self._shown_info = None
            self._apply_power_mode(self.power_mode)

        if self.power_mode == 'standby':
            return                      # SPI/백라이트 정지 — 대기 전력 절감

        with self.gif_lock:
            if not self.gif_frames:
                return

            frame_to_show = self.gif_frames[self.current_frame_index]
            self.current_frame_index = (self.current_frame_index + self.play_frame_skip) % len(self.gif_frames)

        self._lcd('img_show', frame_to_show)


def main(args=None):
    rclpy.init(args=args)
    emotion_node = RosyEmotion()

    try:
        rclpy.spin(emotion_node)
    except KeyboardInterrupt:
        emotion_node.get_logger().info("KeyboardInterrupt, shutting down.")
    finally:
        emotion_node.lcd.clear()
        emotion_node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
