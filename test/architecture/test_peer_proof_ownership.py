"""Keep the shared proof bytes equal without joining CORE/Fleet dependencies."""

from pathlib import Path
import ast


def test_core_and_fleet_peer_proof_copies_are_equal():
    root = Path(__file__).resolve().parents[2]
    core = root / 'middleware/core/api/core_api_web/api/peer_pairing/peer_crypto.py'
    fleet = root / 'operations/fleet/fleet/server/peer/camera_peer_crypto.py'
    assert core.read_bytes() == fleet.read_bytes(), 'Update both independently shipped proof helpers together'


def test_core_and_fleet_tls_verification_match():
    root = Path(__file__).resolve().parents[2]
    paths = ('middleware/core/api/core_api_web/api/peer_pairing/tls_anchor.py',
             'operations/fleet/fleet/server/peer/camera_peer_tls.py')
    checks = []
    for path in paths:
        tree = ast.parse((root / path).read_text(encoding='utf-8'))
        optional_import = next((node for node in tree.body if isinstance(node, ast.Try)), None)
        assert optional_import is not None, f'{path} must handle cryptography<42 at import time'
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        block = next(node for node in functions[-1].body if isinstance(node, ast.Try))
        guard = block.body[0]
        assert isinstance(guard, ast.If) and ast.unparse(guard.test) == 'PolicyBuilder is None'
        # Transport-specific reads and error text differ; trust/validity/chain checks must match.
        start = next(i for i, node in enumerate(block.body)
                     if isinstance(node, ast.If) and ast.unparse(node.test).startswith('len(roots)'))
        statements = block.body[start:]
        for statement in statements:
            for node in ast.walk(statement):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                    node.exc.args = []
        checks.append([ast.dump(node) for node in statements])
    assert checks[0] == checks[1], 'Update both independently shipped TLS verification bodies together'
