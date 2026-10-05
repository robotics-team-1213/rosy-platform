#!/usr/bin/env python3
"""command_watchdog.py — sim base 입력 감시 bridge (D-426 T5).

CORE(rclpy)와는 별도 수명의 프로세스다: ROS 그래프에서 최신 cmd_vel 을
구독해 그대로 재발행하다가, ``EXPIRY_S``(기본 0.30 monotonic s) 동안 새
명령이 없으면 base 입력을 0으로 만든다. CORE 의 operational cmd_vel
writer 권한을 늘리지 않는다(재발행은 시뮬 base 입력에만 적용).

clock pause 에도 만료는 작동한다 — 판정은 monotonic 시계로 한다.

rclpy 가 없는 호스트에서는 이 모듈의 순수 판정(gate)만 시험이 돌린다.

수동 실행은 --sim-only, ROS_DOMAIN_ID=120..199, ROS_LOCALHOST_ONLY=1,
GZ_PARTITION=d426-<run_id>, ROS namespace /rosy_01../rosy_08이 모두 필요하다.
ROSY_RUNTIME_MODE=hardware/motor에서는 실행하지 않는다. 런처·base 연결은 별도다.
"""

from __future__ import annotations

import sys
import time
import math
import os
import re

EXPIRY_S = 0.30
ZERO = (0.0, 0.0)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def gate(last_command_mono: float | None, now_mono: float, *,
         expiry_s: float = EXPIRY_S):
    """현재 내보낼 (linear, angular).

    - 명령을 한 번도 받지 않았다면 0 을 낸다(기다리지 않는다 — 시뮬 base 는
      시작부터 멈춰 있어야 한다).
    - 마지막 명령으로부터 expiry_s 안이면 그 명령을 그대로 흘린다.
    - 만료되면 0 을 낸다(CORE 사망·bridge 단절·명령 끊김 모두 같은 결과).
    """
    if not _finite(now_mono) or not _finite(expiry_s) or now_mono < 0 or expiry_s <= 0:
        return ZERO, 'invalid-clock-or-expiry'
    if last_command_mono is None:
        return ZERO, "no-command"
    if not _finite(last_command_mono) or last_command_mono < 0:
        return ZERO, 'invalid-command-clock'
    age = now_mono - last_command_mono
    if age < 0:
        return ZERO, "clock-went-backwards"
    if age > expiry_s:
        return ZERO, "expired"
    return None, "pass"      # None = 마지막 명령을 그대로


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--help" in argv:
        import sys as _sys

        _sys.stdout.reconfigure(encoding=os.environ.get("PYTHONIOENCODING", "utf-8"),
                                errors="replace")
        print(__doc__)
        return 0
    if (argv.count('--sim-only') != 1
            or not re.fullmatch(r'1[2-9][0-9]', os.environ.get('ROS_DOMAIN_ID', ''))
            or os.environ.get('ROS_LOCALHOST_ONLY') != '1'
            or not re.fullmatch(r'd426-[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', os.environ.get('GZ_PARTITION', ''))
            or os.environ.get('ROSY_RUNTIME_MODE', '') not in ('', 'core')):
        print('command_watchdog requires explicit isolated SIM run scope; see --help', file=sys.stderr)
        return 3
    argv.remove('--sim-only')
    try:
        import rclpy
        from rclpy.clock import Clock, ClockType
        from geometry_msgs.msg import Twist
    except ImportError:
        print("command_watchdog needs ROS 2 (rclpy); the pure gate is host-tested",
              file=sys.stderr)
        return 3

    rclpy.init(args=argv)
    if rclpy.get_default_context().get_domain_id() != int(os.environ['ROS_DOMAIN_ID']):
        rclpy.shutdown()
        print('command_watchdog ROS context differs from the isolated domain', file=sys.stderr)
        return 3
    node = rclpy.create_node("sim_base_command_watchdog")
    namespace = (node.get_namespace() or "").rstrip('/')
    output_topic, input_topic = f'{namespace}/cmd_vel_watchdog', f'{namespace}/cmd_vel'
    if (not re.fullmatch(r'/rosy_0[1-8]', namespace)
            or node.resolve_topic_name(output_topic) != output_topic
            or node.resolve_topic_name(input_topic) != input_topic):
        node.destroy_node()
        rclpy.shutdown()
        print('command_watchdog requires isolated namespace and unchanged SIM topics', file=sys.stderr)
        return 3
    state = {"last": None, "value": ZERO}

    def on_command(message):
        values = (message.linear.x, message.linear.y, message.linear.z,
                  message.angular.x, message.angular.y, message.angular.z)
        if (not all(_finite(value) for value in values)
                or any(value != 0 for value in values[1:5])
                or abs(values[0]) > .15 or abs(values[5]) > .5):
            state['last'], state['value'] = None, ZERO
            return
        state["last"] = time.monotonic()
        state["value"] = (float(message.linear.x), float(message.angular.z))

    publisher = node.create_publisher(Twist, output_topic, 10)
    node.create_subscription(Twist, input_topic, on_command, 10)

    def tick():
        emitted, why = gate(state["last"], time.monotonic())
        if emitted is None:
            emitted = state["value"]
        message = Twist()
        message.linear.x, message.angular.z = emitted
        publisher.publish(message)
        if why != "pass":
            node.get_logger().debug(f"watchdog holding zero: {why}")

    timer = node.create_timer(0.05, tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        timer.cancel()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
