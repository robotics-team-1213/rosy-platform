"""Read-only inventory of registered ROSY design sources; no browser/cascade claims."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = r"--[A-Za-z_][A-Za-z0-9_-]*"
LAYOUT = re.compile(
    r"^(?:display|position|inset(?:-.+)?|top|right|bottom|left|float|clear|"
    r"(?:min-|max-)?(?:width|height|inline-size|block-size)|box-sizing|"
    r"(?:padding|margin|gap|row-gap|column-gap)(?:-.+)?|"
    r"(?:grid|flex|align|justify|place|overflow|contain|container|aspect-ratio|"
    r"object-fit|object-position|order|z-index|transform|resize|border-radius|"
    r"table-layout|columns?|column|break|white-space|word-break|overflow-wrap|"
    r"text-overflow|line-clamp|writing-mode|visibility)(?:-.+)?)$"
)
EXCLUDED = {"test", "tests", "__pycache__", "node_modules", "vendor", "build", "dist", "generated"}


def mask_comments(text: str, javascript: bool = False) -> str:
    """Blank comments, preserving offsets, quoted strings and line numbers."""
    chars = list(text)
    i, quote = 0, None
    while i < len(text):
        if quote:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == quote:
                quote = None
        elif text[i] in "\"'`":
            quote = text[i]
        elif text.startswith("/*", i) or (javascript and text.startswith("//", i)):
            end = text.find("*/", i + 2) + 2 if text[i + 1] == "*" else text.find("\n", i)
            if end < i + 2:
                end = len(text)
            for n in range(i, end):
                if chars[n] != "\n":
                    chars[n] = " "
            i = end
            continue
        i += 1
    return "".join(chars)


def line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def css_declarations(text: str, path: str) -> list[dict]:
    """Track nested rule context and balanced declaration values, including strings."""
    text = mask_comments(text)
    stack, rows = [], []
    start, depth, quote = 0, 0, None
    for i, char in enumerate(text):
        if quote:
            if char == quote:
                backslashes, before = 0, i - 1
                while before >= 0 and text[before] == "\\":
                    backslashes += 1
                    before -= 1
                if backslashes % 2 == 0:
                    quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if depth:
            continue
        if char == "{":
            stack.append(" ".join(text[start:i].split()))
            start = i + 1
        elif char in ";}":
            segment = text[start:i]
            match = re.match(r"\s*(--[\w-]+|[a-zA-Z][\w-]*)\s*:\s*([\s\S]+)", segment)
            if match and stack:
                context = " / ".join(stack)
                themes = re.findall(r'data-theme\s*=\s*[\"\']([^\"\']+)', context)
                rows.append({"path": path, "line": line_at(text, start + match.start(1)),
                             "selector": stack[-1], "context": stack.copy(),
                             "themes": themes, "property": match[1],
                             "value": " ".join(match[2].split())})
            if char == "}" and stack:
                stack.pop()
            start = i + 1
    return rows


def var_references(text: str) -> list[dict]:
    """Record nested var calls individually; a comma makes that call optional."""
    found = []
    for match in re.finditer(r"\bvar\(\s*(" + NAME + r")", text):
        if not re.match(r"\s*[,)]", text[match.end():]):
            continue  # A template such as --text-${role} is a dynamic name, not --text-.
        i, depth, optional = match.end(), 1, False
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            elif text[i] == "," and depth == 1:
                optional = True
            i += 1
        found.append({"name": match[1], "line": line_at(text, match.start()),
                      "optional": optional, "kind": "css-var"})
    return found


def parse_asset(path: str, text: str) -> dict:
    suffix = Path(path).suffix
    clean = mask_comments(text, suffix in {".js", ".mjs"})
    if suffix in {".js", ".mjs", ".html"}:
        clean = re.sub(r"`([^`]*)`", lambda m: "`" + mask_comments(m[1]) + "`", clean)
    if suffix == ".html":
        clean = re.sub(r"<!--[\s\S]*?-->", lambda m: re.sub(r"[^\n]", " ", m[0]), clean)
        chunks = []
        for match in re.finditer(r"<style\b[^>]*>([\s\S]*?)</style\s*>", clean, re.I):
            chunks.append("\n" * clean.count("\n", 0, match.start(1)) + match[1])
    elif suffix == ".css":
        chunks = [clean]
    else:
        # Embedded stylesheet template literals remain source evidence, never evaluated.
        chunks = ["\n" * clean.count("\n", 0, m.start(1)) + m[1]
                  for m in re.finditer(r"`([^`]*\{[^`]*:[^`]*)`", clean)]
    declarations = [row for chunk in chunks for row in css_declarations(chunk, path)]
    uses = var_references(clean)
    excluded = []
    if suffix in {".js", ".mjs", ".html"}:
        for match in re.finditer(r"([\"'])((?:--)[A-Za-z_][A-Za-z0-9_-]*)\1", clean):
            prefix = clean[max(0, match.start() - 100):match.start()]
            if re.search(r"\b\w*BOUNDARY\w*\s*=\s*$", prefix, re.I):
                excluded.append({"name": match[2], "path": path, "line": line_at(clean, match.start()),
                                 "reason": "Boundary constant; no CSS token lookup context"})
                continue
            uses.append({"name": match[2], "line": line_at(clean, match.start(2)),
                         "optional": False, "kind": "js-token-getter" if re.search(
                             r"(?:getPropertyValue|readColour|cssColor)\(\s*$", prefix) else "js-literal-candidate"})
    for row in uses:
        row["path"] = path
    dynamic = [{"path": path, "line": line_at(clean, m.start()), "expression": m[0]}
               for m in re.finditer(r"--[\w-]*\$\{[^}]+\}", clean)]
    return {"declarations": declarations, "uses": uses, "dynamic_names": dynamic, "excluded_literals": excluded}


def component_definitions(path: str, text: str) -> list[dict]:
    clean = mask_comments(text, True)
    found = [(m[2], m.start()) for m in re.finditer(
        r"customElements\.define\(\s*([\"'])(ui-[\w-]+)\1", clean)]
    for loop in re.finditer(r"for\s*\(const\s*\[[^]]+\]\s+of\s+\[([\s\S]*?)\]\)\s*\{([^}]+)\}", clean):
        if "customElements.define" not in loop[2]:
            continue
        found.extend((m[2], loop.start(1) + m.start()) for m in re.finditer(
            r"\[\s*([\"'])(ui-[\w-]+)\1\s*,", loop[1]))
    return [{"path": path, "line": line_at(clean, offset), "name": name} for name, offset in found]


def expand(value: str, declarations: dict[str, str], seen: tuple = ()) -> str:
    """Expand aliases as expressions; colour functions deliberately stay expressions."""
    def replacement(match):
        name = match[1]
        if name in seen:
            return f"<cycle:{name}>"
        if name not in declarations:
            return match[0]
        return expand(declarations[name], declarations, seen + (name,))
    return re.sub(r"var\(\s*(" + NAME + r")\s*\)", replacement, value)


def local_kind(row: dict) -> str:
    if re.search(r"(?:percent|progress|angle|rotation|zoom|pan|offset|cursor|pointer|"
                 r"viewport|rect|pixel|canvas|mask|clip|thumb|range|(?:^|-)x$|(?:^|-)y$)", row["property"]):
        return "inferred-runtime-or-data-geometry"
    return "component-or-surface-local"


def build_inventory(root: Path, surfaces: list[dict], files: dict[str, str]) -> dict:
    parsed = {path: parse_asset(path, text) for path, text in sorted(files.items())}
    canonical_path = "shared/web/tokens.css"
    canonical = [row for row in parsed[canonical_path]["declarations"] if row["property"].startswith("--")]
    names = {row["property"] for row in canonical}
    themes = sorted({theme for row in canonical for theme in row["themes"]})
    tokens = []
    for name in sorted(names):
        expressions = {}
        for theme in themes:
            values = {r["property"]: r["value"] for r in canonical
                      if not r["themes"] or theme in r["themes"]}
            if name in values:
                expressions[theme] = expand(values[name], values, (name,))
        occurrences = [dict(row, dependencies=sorted({r["name"] for r in var_references(row["value"])}))
                       for row in canonical if row["property"] == name]
        tokens.append({"name": name, "occurrences": occurrences, "theme_expressions": expressions})
    locals_ = [dict(row, classification=local_kind(row), canonical_override=row["property"] in names)
               for path, asset in parsed.items() if path != canonical_path
               for row in asset["declarations"] if row["property"].startswith("--")]
    common = {path for path in parsed if path.startswith("shared/web/")}
    surface_rows = []
    for surface in surfaces:
        prefix = surface["path"].rstrip("/")
        owned = {path for path in parsed if path == prefix or path.startswith(prefix + "/")}
        accessible = owned | common
        declared = names | {row["property"] for path in accessible
                            for row in parsed[path]["declarations"] if row["property"].startswith("--")}
        missing = [dict(use, surface=surface["id"]) for path in sorted(owned)
                   for use in parsed[path]["uses"] if not use["optional"] and use["name"] not in declared]
        surface_rows.append({"metadata": surface, "assets": sorted(owned),
                             "grammars": sorted({m[2] for path in owned if path.endswith(".html")
                                                 for m in re.finditer(r'\bgrammar\s*=\s*([\"\'])([^\"\']+)\1', files[path])}),
                             "missing_reference_candidates": missing})
    layout = [row for asset in parsed.values() for row in asset["declarations"] if LAYOUT.fullmatch(row["property"])]
    uses = [row for asset in parsed.values() for row in asset["uses"]]
    components = [row for path, text in sorted(files.items()) if path.startswith("shared/web/")
                  for row in component_definitions(path, text)]
    copies = []
    for surface in surfaces:
        source = surface.get("token_copy")
        if source and (root / source).is_file():
            for number, line in enumerate((root / source).read_text(encoding="utf-8").splitlines(), 1):
                match = re.search(r"(?:#|//)\s*(--[\w-]+)", line)
                if match:
                    copies.append({"surface": surface["id"], "path": source, "line": number,
                                   "name": match[1], "source": line.strip()})
    return {"schema_version": 1, "scope": "Registered runtime assets and shared/web; static source inventory",
            "limitations": ["Availability is checked per registered surface plus common sources, not per page or CSS selector.",
                            "No CSS cascade, media activation, runtime DOM, browser paint, or actual colour evaluation is simulated.",
                            "JS string names are candidates; dynamic names and runtime writers require manual review.",
                            "Native/LCD copy annotations are listed; native runtime Kotlin/Gradle use sites are not scanned. Generator and verification paths remain registry metadata.",
                            "Local geometry classification is inferred from names, not a design-contract exemption."],
            "summary": {"surfaces": len(surfaces), "assets": len(files), "unique_tokens": len(tokens),
                        "canonical_declarations": len(canonical), "local_declarations": len(locals_),
                        "uses": len(uses), "layout_declarations": len(layout), "components": len(components),
                        "missing_reference_candidates": sum(len(r["missing_reference_candidates"]) for r in surface_rows)},
            "surfaces": surface_rows, "tokens": tokens, "local_custom_properties": locals_,
            "uses": uses, "layout_declarations": layout, "components": components, "token_copies": copies,
            "dynamic_names": [r for a in parsed.values() for r in a["dynamic_names"]],
            "excluded_literal_candidates": [r for a in parsed.values() for r in a["excluded_literals"]]}


def discover(root: Path) -> tuple[list[dict], dict[str, str]]:
    """Use the existing registry's duplicate-key-safe YAML reader and Git discovery."""
    sys.path.insert(0, str(root / "shared/web/test"))
    import surface_registry

    surfaces = surface_registry.load(root)
    output = subprocess.run(["git", "-C", str(root), "ls-files", "-cz", "--others", "--exclude-standard"],
                            check=True, capture_output=True).stdout.decode("utf-8")
    roots = [row["path"].rstrip("/") for row in surfaces if row.get("medium") == "web"] + ["shared/web"]
    files = {}
    for path in sorted(set(output.split("\0")) - {""}):
        parts = Path(path).parts
        if (Path(path).suffix not in {".css", ".js", ".mjs", ".html"}
                or EXCLUDED.intersection(parts) or ".min." in path
                or not any(path == base or path.startswith(base + "/") for base in roots)):
            continue
        files[path] = (root / path).read_text(encoding="utf-8")
    return surfaces, files


def markdown(data: dict, compact: bool = False) -> str:
    def cell(value):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        return str(value).replace("|", "&#124;").replace("\n", " ")

    def table(headers, rows):
        return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + [
            "| " + " | ".join(cell(value) for value in row) + " |" for row in rows]

    out = ["# ROSY UI design source inventory", "", data["scope"], "", json.dumps(data["summary"], ensure_ascii=False), ""]
    out += ["Generated by `python tools/ui_design_inventory.py --format " + ("tokens-markdown" if compact else "markdown") + "`.",
            "[DESIGN.md](https://github.com/robotics-team-1213/rosy-platform/blob/main/DESIGN.md) and its referenced ADRs own design policy; this inventory describes source occurrences.", ""]
    out += ["- " + limitation for limitation in data["limitations"]]
    out += ["", "## Surfaces and authoritative registry metadata", ""]
    if compact:
        out += table(["Surface", "Medium", "Grammar", "Themes", "Path", "Assets"], [
            (r["metadata"]["id"], r["metadata"].get("medium", ""), r["grammars"],
             r["metadata"].get("themes", []), r["metadata"]["path"], len(r["assets"])) for r in data["surfaces"]])
    else:
        out += table(["Surface", "Metadata", "Assets"], [(r["metadata"]["id"], r["metadata"], r["assets"]) for r in data["surfaces"]])
    out += ["", "## Canonical tokens — every declaration occurrence", ""]
    out += table(["Name", "Source", "Selector/context", "Themes", "Value", "Dependencies"], [
        (t["name"], f'{r["path"]}:{r["line"]}', r["context"], r["themes"], r["value"], r["dependencies"])
        for t in data["tokens"] for r in t["occurrences"]])
    out += ["", "## Token expressions by theme (functions are not resolved RGB)", ""]
    out += table(["Name", "Theme expressions", "Static uses", "Source files"], [
        (t["name"], t["theme_expressions"], sum(r["name"] == t["name"] for r in data["uses"]),
         len({r["path"] for r in data["uses"] if r["name"] == t["name"]})) for t in data["tokens"]])
    out += ["", "## Local custom properties and common overrides", ""]
    out += table(["Name", "Source", "Selector", "Value", "Classification", "Canonical override"], [
        (r["property"], f'{r["path"]}:{r["line"]}', r["selector"], r["value"], r["classification"], r["canonical_override"])
        for r in data["local_custom_properties"]])
    if compact:
        out += ["", "## Custom element definitions", ""]
        out += table(["Name", "Source"], [(r["name"], f'{r["path"]}:{r["line"]}') for r in data["components"]])
        out += ["", "## Native/LCD copy annotations", ""]
        out += table(["Name", "Source", "Declaration"], [(r["name"], f'{r["path"]}:{r["line"]}', r["source"]) for r in data["token_copies"]])
        out += ["", "Full layout declarations, reference occurrences, dynamic names, and missing candidates are in the JSON inventory."]
        return "\n".join(out) + "\n"
    out += ["", "## Layout declarations", ""]
    out += table(["Source", "Context", "Property", "Value"], [
        (f'{r["path"]}:{r["line"]}', r["context"], r["property"], r["value"]) for r in data["layout_declarations"]])
    out += ["", "## Reference occurrences", ""]
    out += table(["Name", "Source", "Kind", "Fallback optional"], [
        (r["name"], f'{r["path"]}:{r["line"]}', r["kind"], r["optional"]) for r in data["uses"]])
    out += ["", "## Missing reference candidates by surface", ""]
    out += table(["Surface", "Name", "Source", "Kind"], [
        (r["surface"], r["name"], f'{r["path"]}:{r["line"]}', r["kind"])
        for surface in data["surfaces"] for r in surface["missing_reference_candidates"]])
    out += ["", "## Custom element definitions", ""]
    out += table(["Name", "Source"], [(r["name"], f'{r["path"]}:{r["line"]}') for r in data["components"]])
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["json", "markdown", "tokens-markdown"], default="json")
    args = parser.parse_args()
    surfaces, files = discover(ROOT)
    data = build_inventory(ROOT, surfaces, files)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.format == "json"
          else markdown(data, compact=args.format == "tokens-markdown"))


if __name__ == "__main__":
    main()
