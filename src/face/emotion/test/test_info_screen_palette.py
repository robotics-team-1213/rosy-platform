"""concept 16 L1 / D-82 — 얼굴 화면 팔레트의 수치 게이트.

L1(토큰)은 네 표면이 공유한다. 이 모듈은 자기 색 사본을 갖고 있으므로
(D-73: 기능 시험은 그 모듈이 소유한 코드만 단언한다) 같은 성질을 여기서
따로 지킨다. core의 tokens.css를 가로질러 단언하지 않는다.

이 시험이 존재하는 이유: 이전 값은 적록 색약 시야에서 _WARN 대 _CRIT 대비가
1.26:1이었다. 얼굴은 1.5m 밖에서 0.5초에 읽히는 화면인데, 하필 제일 중요한
쌍인 주의와 위험이 구분되지 않았다.

표준 라이브러리만 쓴다 — PIL 없이도 돈다.
"""

import math
import unittest

from emotion.info_screen import _BG, _CRIT, _FG, _MUTED, _NOMINAL, _WARN


def _linear(channel: int) -> float:
    v = channel / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _encode(value: float) -> int:
    value = max(0.0, min(1.0, value))
    srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return max(0, min(255, round(srgb * 255)))


def oklch(rgb):
    r, g, b = (_linear(c) for c in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    lightness = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return lightness, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def luminance(rgb):
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    ya, yb = luminance(a), luminance(b)
    return (max(ya, yb) + 0.05) / (min(ya, yb) + 0.05)


def deuteranope(rgb):
    r, g, b = (_linear(c) for c in rgb)
    return (
        _encode(0.625 * r + 0.375 * g),
        _encode(0.700 * r + 0.300 * g),
        _encode(0.300 * g + 0.700 * b),
    )


class InfoScreenPaletteTest(unittest.TestCase):
    def test_caution_and_danger_never_collapse(self):
        """지나가면서 보는 화면에서 주의와 위험이 같은 색이 되면 안 된다."""
        delta_l = abs(oklch(_WARN)[0] - oklch(_CRIT)[0])
        self.assertGreaterEqual(delta_l, 0.15, f"지각 밝기 차 {delta_l:.3f}")

        simulated = contrast(deuteranope(_WARN), deuteranope(_CRIT))
        self.assertGreaterEqual(
            simulated, 2.0, f"색약 대비 {simulated:.2f}:1 (이전 값은 1.26:1)"
        )

    def test_nominal_carries_no_colour(self):
        """정상에는 색이 없다 — 배터리가 넉넉하면 잉크로 쓴다."""
        self.assertEqual(_NOMINAL, _FG)
        self.assertLessEqual(
            oklch(_NOMINAL)[1], 0.02, "정상 색에 채도가 있다"
        )

    def test_signal_colours_carry_enough_chroma(self):
        for name, value in (("_WARN", _WARN), ("_CRIT", _CRIT)):
            with self.subTest(colour=name):
                self.assertGreaterEqual(oklch(value)[1], 0.133)

    def test_text_reads_on_the_lcd_ground(self):
        """작은 화면, 먼 거리. 본문은 4.5:1, 큰 숫자는 3:1."""
        self.assertGreaterEqual(contrast(_FG, _BG), 4.5)
        self.assertGreaterEqual(contrast(_MUTED, _BG), 4.5)
        self.assertGreaterEqual(contrast(_WARN, _BG), 4.5)
        # _CRIT은 56px 굵은 숫자에만 쓰인다 — 큰 글자 기준 3:1.
        self.assertGreaterEqual(contrast(_CRIT, _BG), 3.0)

    def test_the_ground_is_neutral(self):
        for name, value in (("_BG", _BG), ("_FG", _FG), ("_MUTED", _MUTED)):
            with self.subTest(colour=name):
                self.assertLessEqual(oklch(value)[1], 0.03)


if __name__ == "__main__":
    unittest.main()
