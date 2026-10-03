"""Inventory ROS endpoint/frame expressions without importing nodes or drivers.

This is a source audit, not a runtime graph validator. Launch remaps, YAML
overrides and computed names still require live ROS verification.
"""
import argparse
import ast
import csv
from collections import Counter
from pathlib import Path


def inventory(package):
    rows = []
    endpoints = {'create_publisher', 'create_subscription', 'create_client', 'create_service'}
    for path in sorted(package.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        defaults = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'declare_parameter' and len(node.args) > 1
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[1], ast.Constant)):
                defaults[node.args[0].value] = node.args[1].value

        def add(node, kind, value):
            expression = ast.unparse(value)
            default = value.value if isinstance(value, ast.Constant) else None
            if (isinstance(value, ast.Attribute) and value.attr == 'value'
                    and isinstance(value.value, ast.Call)
                    and isinstance(value.value.func, ast.Attribute)
                    and value.value.func.attr == 'get_parameter' and value.value.args
                    and isinstance(value.value.args[0], ast.Constant)):
                default = defaults.get(value.value.args[0].value)
            if isinstance(default, str):
                scope = 'absolute' if default.startswith('/') else 'relative_or_frame'
            else:
                scope = 'dynamic_unresolved'
            rows.append(dict(source=path.relative_to(package).as_posix(), line=node.lineno,
                             kind=kind, expression=expression,
                             declared_default=default if isinstance(default, str) else '',
                             scope=scope))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                method = node.func.attr
                if method in endpoints and len(node.args) > 1:
                    add(node, method, node.args[1])
                elif method == 'lookup_transform':
                    for index, value in enumerate(node.args[:2]):
                        add(node, 'tf_target' if index == 0 else 'tf_source', value)
                elif (method == 'declare_parameter' and len(node.args) > 1
                      and isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str)
                      and any(key in node.args[0].value for key in ('topic', 'frame', 'path'))):
                    add(node, 'parameter:' + node.args[0].value, node.args[1])
            elif isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Attribute) and target.attr == 'frame_id'
                       for target in node.targets):
                    add(node, 'frame_assignment', node.value)
    return sorted(rows, key=lambda row: (row['source'], row['line'], row['kind']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1] / 'control'
    rows = inventory(package)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            'source', 'line', 'kind', 'expression', 'declared_default', 'scope'])
        writer.writeheader()
        writer.writerows(rows)
    endpoint_rows = [r for r in rows if r['kind'].startswith('create_')]
    print(dict(rows=len(rows), endpoints=len(endpoint_rows),
               endpoint_scope=dict(Counter(row['scope'] for row in endpoint_rows))))


if __name__ == '__main__':
    main()
