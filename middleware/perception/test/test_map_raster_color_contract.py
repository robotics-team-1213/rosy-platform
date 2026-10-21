"""concept 16 §6 — /map.png의 색과 콘솔 캔버스의 색은 같은 값이어야 한다.

서버는 `sensing/map_raster.py`가 굽고 클라이언트는 `web/diagnostic.html`이
그린다. 두 값이 어긋나면 오버레이가 섞이지 않고, 예전에 실제로 어긋나 있었다:
RGB 튜플이 BGR 배열에 그대로 들어가 PNG의 벽 색이 #e1e0d9가 아니라
#d9e0e1로 나왔다.

이 시험은 소스를 텍스트로 읽는다. `map_raster.py`를 import하면 numpy가
따라오는데 CI 의존 목록에 numpy가 없다(D-73: 이 모듈이 소유한 파일만 단언).
"""
import ast
import re
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RASTER = PACKAGE_ROOT / 'sensors' / 'sensing' / 'map_raster.py'
CONSOLE = PACKAGE_ROOT / 'web' / 'diagnostic.html'


def server_rgb():
    """`OCCUPANCY_RGB` 리터럴을 실행 없이 읽는다."""
    tree = ast.parse(RASTER.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if 'OCCUPANCY_RGB' in names:
            return {
                key.value: tuple(ast.literal_eval(value))
                for key, value in zip(node.value.keys, node.value.values)
            }
    raise AssertionError('map_raster.py에 OCCUPANCY_RGB 선언이 없다')


def console_tokens():
    text = CONSOLE.read_text(encoding='utf-8')
    found = {}
    for token in ('unk', 'free', 'wall'):
        match = re.search(rf'--{token}:\s*#([0-9a-fA-F]{{6}})', text)
        assert match, f'diagnostic.html에 --{token} 토큰이 없다'
        found[token] = match.group(1).lower()
    return found


class MapRasterColorContractTest(unittest.TestCase):
    NAMES = (('unknown', 'unk'), ('free', 'free'), ('wall', 'wall'))

    def test_server_raster_matches_the_console_canvas(self):
        server = server_rgb()
        console = console_tokens()

        for server_key, token in self.NAMES:
            with self.subTest(color=server_key):
                rendered = '%02x%02x%02x' % server[server_key]
                self.assertEqual(
                    rendered,
                    console[token],
                    f'{server_key}: PNG는 #{rendered}, 캔버스는 #{console[token]}',
                )

    def test_bgr_is_derived_and_not_written_by_hand(self):
        """BGR을 손으로 적으면 채널 역전이 다시 생긴다. 파생이어야 한다."""
        source = RASTER.read_text(encoding='utf-8')
        self.assertIn('OCCUPANCY_BGR', source)
        self.assertRegex(
            source,
            r'OCCUPANCY_BGR\s*=\s*\{[^}]*reversed\(',
            'OCCUPANCY_BGR은 OCCUPANCY_RGB에서 뒤집어 파생해야 한다',
        )

    def test_the_canvas_reads_its_colours_from_the_css_roles(self):
        """캔버스 색은 사본이 아니라 :root 속성 이름이다(D-77). 값은 그리는 순간 RosyPalette가 푼다."""
        text = CONSOLE.read_text(encoding='utf-8')
        root = text.split('<style>', 1)[1].split('}', 1)[0]
        declared = set(re.findall(r'--([a-z0-9-]+):', root))
        block = re.search(r'const T_VARS = \{([^}]+)\}', text)
        self.assertIsNotNone(block, 'diagnostic.html에 const T_VARS 표가 없다')
        self.assertNotRegex(block.group(1), r'#[0-9a-fA-F]{3,8}', 'T_VARS에 원시 색이 있다')
        names = re.findall(r"\w+:\s*'--([a-z0-9-]+)'", block.group(1))
        shared = {'ink', 'ink-quiet', 'line-06', 'line-50'}  # tokens.css, loaded before the page sheet
        missing = [name for name in names if name not in declared | shared]
        self.assertTrue(names)
        self.assertFalse(missing, f':root에 없는 T 속성: {missing}')


if __name__ == '__main__':
    unittest.main()
