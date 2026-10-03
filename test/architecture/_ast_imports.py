"""Static import extraction shared by the D-413 and D-427 boundary tests."""

import ast


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _imports(source: str, package_name: str) -> list[str]:
    tree = ast.parse(source)
    imported = []
    package_parts = package_name.split(".") if package_name else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                ascend = node.level - 1
                base = package_parts[:max(0, len(package_parts) - ascend)]
                prefix = ".".join(base)
            else:
                prefix = ""
            if node.module:
                imported.append(".".join(part for part in (prefix, node.module) if part))
                for alias in node.names:
                    if alias.name != "*":
                        imported.append(".".join(part for part in (prefix, node.module, alias.name) if part))
            elif node.level:
                for alias in node.names:
                    if alias.name != "*":
                        imported.append(".".join(part for part in (prefix, alias.name) if part))
    return imported
