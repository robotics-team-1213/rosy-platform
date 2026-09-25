"""Find every create_subscription call in the control package (D-185 R2 contract).

Resolves a literal topic, a topic built from a for-loop over literal tuples
(`for topic in ('/a', '/b'): ... topic.lstrip('/')`), and qos passed positionally or
as ``qos_profile=``. Unresolvable topics are reported, never skipped.
"""
import ast
from pathlib import Path

CONTROL = Path(__file__).resolve().parents[1]/'control'


def _literal_rows(node, assignments):
    """Elements of a literal tuple/list, following one module-level name if needed."""
    if isinstance(node, ast.Name):
        node = assignments.get(node.id)
    return node.elts if isinstance(node, (ast.Tuple, ast.List)) else None


def _loop_values(tree):
    """Map each for-loop target name to the literal topic strings it iterates over.

    Handles `for topic in ('/a', '/b')` and `for topic, typ, key in TABLE` where TABLE is a
    module-level list of tuples whose first element is the topic string.
    """
    assignments = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
    values = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        rows = _literal_rows(node.iter, assignments)
        if rows is None:
            continue
        if isinstance(node.target, ast.Name):
            name, picks = node.target.id, rows
        elif isinstance(node.target, ast.Tuple) and isinstance(node.target.elts[0], ast.Name):
            name = node.target.elts[0].id
            picks = [row.elts[0] for row in rows if isinstance(row, ast.Tuple) and row.elts]
        else:
            continue
        if picks and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in picks):
            values.setdefault(name, []).extend(e.value for e in picks)
    return values


def _topics(argument, loops):
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return [argument.value]
    base = argument.func.value if (isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute)
                                   and argument.func.attr == 'lstrip') else argument
    if isinstance(base, ast.Name) and base.id in loops:
        return [value.lstrip('/') for value in loops[base.id]]
    return None


def subscriptions():
    """[(relative path, topic or None, qos node, callback source, line)] for the whole package."""
    found = []
    for path in sorted(CONTROL.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        loops = _loop_values(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'create_subscription'):
                continue
            keywords = {k.arg: k.value for k in node.keywords}
            topic = node.args[1] if len(node.args) > 1 else keywords.get('topic')
            callback = node.args[2] if len(node.args) > 2 else keywords.get('callback')
            qos = node.args[3] if len(node.args) > 3 else keywords.get('qos_profile')
            relative = path.relative_to(CONTROL).as_posix()
            for name in (_topics(topic, loops) if topic is not None else None) or [None]:
                found.append((relative, name, qos, ast.unparse(callback) if callback is not None else '',
                              node.lineno))
    return found


if __name__ == '__main__':
    fresh = {'safety/decision', 'safety/motion_limits', 'safety/observation', 'safety/can_reverse',
             'safety/blocked', 'safety/cliff', 'safety/tilt', 'safety/pickup', 'cmd_vel_raw'}
    for relative, topic, qos, callback, line in subscriptions():
        if topic is None or topic in fresh or 'on_cmd' in callback:
            shown = ast.unparse(qos) if qos else None
            print(f'{relative:32} {topic!s:22} qos={shown!s:28} {callback[:40]}:{line}')
