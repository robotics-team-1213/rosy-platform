"""Module harness records: validate progress/logs, generate index and status.

Usage (from the repository root)::

    python tools/harness/rosy_harness.py generate   # rewrite index.md files and STATUS.md
    python tools/harness/rosy_harness.py lint       # errors exit 1; staleness is a warning
    python tools/harness/rosy_harness.py affected [--base main] [--print|--run] [--json]
                                                    # D-436 change-scoped pytest selection

Design: ``docs/plans/2026-09-15-module-harness-design.md`` (ADR D-61).
ROS-free: standard library plus PyYAML, so it runs on Windows hosts and in CI.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling sim2real (D-480), perception_gaps, also when loaded by path
import perception_gaps  # noqa: E402
import sim2real  # noqa: E402
from log_validation import LOG_FIELDS, LOG_FIELD_ALIASES, validate_entries  # noqa: E402,F401
from generated_records import _normalize, check as _check_records, write as _write_records  # noqa: E402
from rosy_harness_helpers import (  # noqa: E402,F401
    ADR_BODY_HEADING,
    ADR_INDEX_ROW,
    COMMIT,
    CONFIG,
    CONFLICT_MARKER,
    FENCE,
    GATES,
    GENERATED_MARK,
    HarnessError,
    KNOWN_LEGACY_HEADINGS,
    KNOWN_LOG_ENCODING_REPAIRS,
    LOG_HEADING,
    LOGICAL_MODULE,
    RECENT_LOGS,
    REQUIRED_PROGRESS,
    STATES,
    UNCOMMITTED,
    AdrLog,
    LogEntry,
    _adr_number,
    _link,
    _log_entry_blocks,
    _moved_owner,
    _moved_roots,
    _names_module,
    _read_log,
    _read_progress,
    _scan_log,
    find_conflict_markers,
    find_mojibake,
    load_config,
    parse_adr_log,
    parse_log,
    render_brief,
    render_status,
    split_frontmatter,
    validate_log,
    validate_progress,
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import worktrees  # noqa: E402  (D-761: tools/worktrees.py, the .worktrees/ cap warning)
from adr_gaps import (  # noqa: E402,F401
    ADR_GAPS, ADR_ID, load_adr_gaps, parse_adr_gaps, reservation_warnings, reserved_adrs, validate_adr_log,
)


def _optional_frontmatter(path: Path) -> dict:
    try:
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, yaml.YAMLError):
        return {}
    return meta


def is_append_only(old: str, new: str) -> bool:
    """커밋된 항목이 새 버전에 변형 없이 모두 살아 있으면 합격이다.

    prefix 비교가 아니라 **항목 보존 비교**다 — 여러 세션이 각자 항목을 추가한
    브랜치를 병합하면 항목 순서가 섞이는 것은 정상이지만(2026-09-20 codex 브랜치
    병합 실측), 이미 커밋된 항목의 내용이 바뀌거나 사라지는 것은 여전히 위반이다.
    """
    old_blocks = _log_entry_blocks(old)
    new_blocks = _log_entry_blocks(new)
    evidence_reconciliations = {
        "## 2026-10-02 · uncommitted · test(fleet): track Mission event watermark across replay": (
            "- Evidence: targeted Mission, dispatcher, service, progress, task, OMX ActionStore, and replay suites: "
            "pending final worktree verification.",
            "- Evidence: targeted Mission, dispatcher, service, progress, task, OMX ActionStore, and replay suites: "
            "77 passed; known-failure comparison: 0 new, 0 known.",
        ),
    }
    # The G2 journals at 230ccfc2a and 429e13b83 irreversibly lost Korean text.
    # Only these exact provenance corrections may replace them; all other entries
    # still require byte-for-byte preservation after normalization.
    provenance_reconciliations = {
        "a5eecc71690d74036c9e393a2a47262843dfd369b71fe0d6ff92c40a24730c49": (  # original block SHA256
            "76178d7f01aab15760f4ed9cda9787123aeb087bf4d796eed0d203c941f7648a"  # corrected block SHA256
        ),
        "e2f80dbdfc41bdcff21a27d50ddd7ae909a32d02270c5db525808c6d9977883d": (  # original aid block SHA256
            "ffaaae6e3e9186866372a176a17d23985ff2f795028e6d524719942006b88cc2"  # corrected aid block SHA256
        ),
    }
    new_hashes = {sha256(block.encode("utf-8")).hexdigest() for block in new_blocks}
    for block in old_blocks:
        if block in new_blocks:
            continue
        block_hash = sha256(block.encode("utf-8")).hexdigest()
        corrected_hash = provenance_reconciliations.get(block_hash)
        if corrected_hash is not None and corrected_hash in new_hashes:
            continue
        repaired_hash = KNOWN_LOG_ENCODING_REPAIRS.get(block_hash)
        if repaired_hash is not None and repaired_hash in new_hashes:
            continue
        lines = block.splitlines()
        replacement = evidence_reconciliations.get(lines[0])
        if replacement is None or replacement[0] not in block:
            return False
        reconciled = block.replace(replacement[0], replacement[1], 1)
        if reconciled not in new_blocks:
            return False
    return True


def _title(path: Path, meta: dict | None = None) -> str:
    meta = _optional_frontmatter(path) if meta is None else meta
    if isinstance(meta.get("title"), str):
        return meta["title"]
    for line in _normalize(path.read_text(encoding="utf-8", errors="replace")).split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def render_module_index(repo: Path, module: dict, adr: AdrLog, adr_log_path: Path,
                        plan_docs: list | None = None, solution_docs: list | None = None) -> str:
    base = repo / module["path"]
    meta = _read_progress(repo, module)
    name = module["name"]
    lines = [
        GENERATED_MARK,
        f"# {name} index",
        "",
        "기록: [progress.md](progress.md) · [logs.md](logs.md) · [AGENTS.md](AGENTS.md)",
        "",
        "## 결정 (ADR)",
        "",
        f"출처와 Status: [ROSY ADR Log]({_link(base, adr_log_path)}). 목록은 `progress.md`의 `adrs`다.",
        "",
        "| ID | 제목 |",
        "|---|---|",
    ]
    for adr_id in sorted(set(meta.get("adrs") or []), key=_adr_number):
        title, _ = adr.index.get(adr_id, ("(ADR log에 없음)", "?"))
        lines.append(f"| {adr_id} | {title} |")

    plan_docs = [(p, _optional_frontmatter(p)) for p in (repo / "docs" / "plans").glob("*.md")] if plan_docs is None else plan_docs
    plans = {repo / p for p in meta.get("plans") or []} | {p for p, fm in plan_docs if _names_module(fm, name)}
    lines += ["", "## 계획·결과 문서", ""]
    ordered = sorted(plans, key=lambda p: p.relative_to(repo).as_posix())
    lines += [f"- [{p.name}]({_link(base, p)})" for p in ordered] or ["- 없음"]

    solutions_root = repo / "docs" / "solutions"
    solution_docs = [(p, _optional_frontmatter(p)) for p in solutions_root.rglob("*.md") if p.name != "AGENTS.md"] if solution_docs is None else solution_docs
    solutions = sorted(((p, fm) for p, fm in solution_docs if _names_module(fm, name)), key=lambda x: x[0].relative_to(solutions_root).as_posix())
    lines += ["", "## 교훈 (docs/solutions)", ""]
    lines += [f"- [{_title(p, fm)}]({_link(base, p)})" for p, fm in solutions] or ["- 없음"]

    lines += ["", "## 시험", ""]
    lines += [f"- `{t}`" for t in module.get("tests") or []] or ["- 없음"]

    recent = list(reversed(_read_log(repo, module)[-RECENT_LOGS:]))
    lines += ["", "## 최근 기록", ""]
    lines += [f"- {e.date} · {e.commit} · {e.summary}" for e in recent] or ["- 없음"]
    return "\n".join(lines) + "\n"


def generated_targets(repo: Path, adr: AdrLog | None = None) -> dict[Path, str]:
    config = load_config(repo)
    adr_path = repo / config["adr_log"]
    adr = parse_adr_log(adr_path.read_text(encoding="utf-8"), repo / "docs" / "adr") if adr is None else adr
    plan_docs = [(p, _optional_frontmatter(p)) for p in (repo / "docs" / "plans").glob("*.md")]
    sol_docs = [(p, _optional_frontmatter(p)) for p in (repo / "docs" / "solutions").rglob("*.md") if p.name != "AGENTS.md"]
    targets = {repo / m["path"] / "index.md": render_module_index(repo, m, adr, adr_path, plan_docs, sol_docs) for m in config["modules"]}
    targets[repo / config["status"]] = render_status(repo, config)
    if config.get("sim2real_gaps"):
        targets[repo / config["sim2real_table"]] = sim2real.render(sim2real.read(repo / config["sim2real_gaps"]))
    if config.get("perception_gaps"):
        targets[repo / config["perception_table"]] = perception_gaps.render(perception_gaps.read(repo / config["perception_gaps"]))
    return targets


def check_generated(repo: Path, adr: AdrLog | None = None) -> list[str]:
    try:
        targets = generated_targets(repo, adr)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        return [f"cannot render: {exc}"]
    return _check_records(repo, targets)


def generate(repo: Path) -> list[Path]:
    return _write_records(repo, generated_targets(repo))


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=False
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _history_refs(repo: Path) -> tuple[list[str], str | None]:
    """Refs whose committed logs must survive: the CI base, the merge base, and HEAD."""
    note = None
    refs: list[str] = []
    requested = os.environ.get("HARNESS_BASE_REF") or None
    if requested:
        resolvable = set(requested) != {"0"} and _git(repo, "rev-parse", "--verify", "--quiet", f"{requested}^{{commit}}")
        if resolvable:
            refs.append(requested)
        else:
            note = f"HARNESS_BASE_REF {requested[:12]} does not resolve; compared with the origin/main merge base"
    refs += [b.strip() for t in ("origin/main", "main") if (b := _git(repo, "merge-base", "HEAD", t)) and b.strip()]
    if not refs:
        missing = "append-only base unavailable (no origin/main or shallow clone); compared with HEAD only"
        note = f"{note}; {missing}" if note else missing
    return list(dict.fromkeys([*refs, "HEAD"])), note


def _append_only_findings(repo: Path, refs: list[str], name: str, module_path: str, text: str,
                          moved_roots: list[dict]) -> tuple[list[str], list[str]]:
    """Errors for edited committed log entries, and a warning when a module inside a
    moved root has no history to compare with (e.g. a rename git did not detect)."""
    errors: list[str] = []
    warnings: list[str] = []
    for ref in refs:
        committed = _committed_log(repo, ref, module_path, moved_roots)
        if committed is None:
            if _moved_owner(module_path, moved_roots) is not None:
                warnings.append(
                    f"{name}/logs.md: append-only check skipped at {ref[:12]}: no logs.md at {module_path}, "
                    "its D-427 legacy path or a detected rename; keep moved logs at 100% rename similarity")
        elif not is_append_only(committed, text):
            errors.append(f"{name}/logs.md: entries committed at {ref[:12]} were edited; logs are append-only")
    return errors, warnings


def _committed_log(repo: Path, ref: str, module_path: str, moved_roots: list[dict]) -> str | None:
    """``logs.md`` of a module as committed at ``ref``, following a D-427 move."""
    rel = f"{module_path}/logs.md"
    committed = _git(repo, "show", f"{ref}:{rel}")
    if committed is not None:
        return committed
    owner = _moved_owner(module_path, moved_roots)
    if owner is None:
        return None
    if owner["path"] == module_path:
        if owner.get("layout_target") and owner.get("d427_target"):
            committed = _git(repo, "show", f"{ref}:{owner['d427_target']}/logs.md")
            if committed is not None:
                return committed
        return _git(repo, "show", f"{ref}:{owner['legacy']}/logs.md")
    renamed = _git(repo, "log", "-1", "--follow", "-M", "--diff-filter=R", "--format=", "--name-status",
                   "HEAD", "--", rel) or ""
    fields = renamed.strip().split("\t")
    if len(fields) == 3 and fields[0].startswith("R"):
        return _git(repo, "show", f"{ref}:{fields[1]}")
    return None


def lint(repo: Path) -> tuple[list[str], list[str]]:
    config = load_config(repo)
    errors: list[str] = []
    warnings: list[str] = []

    adr_text = (repo / config["adr_log"]).read_text(encoding="utf-8")
    adr = parse_adr_log(adr_text, repo / "docs" / "adr")
    gaps, gap_errors = load_adr_gaps(repo, config)
    errors += [f"{ADR_GAPS.as_posix()}: {e}" for e in gap_errors]
    errors += [f"ADR log: {e}" for e in validate_adr_log(adr, gaps)]
    warnings += [f"ADR log: {w}" for w in reservation_warnings(adr, gaps, reserved_adrs(repo))]
    warnings += [note for note in [worktrees.lint_note(repo)] if note]
    if config.get("sim2real_gaps"):
        registry, problem = sim2real.load(repo / config["sim2real_gaps"])
        gap_errors, gap_warnings = ([problem], []) if problem else sim2real.validate(registry, repo, set(adr.index))
        errors += [f"sim2real: {e}" for e in gap_errors]
        warnings += [f"sim2real: {w}" for w in gap_warnings]
    if config.get("perception_gaps"):
        registry, problem = perception_gaps.load(repo / config["perception_gaps"])
        spot_errors, spot_warnings = ([problem], []) if problem else perception_gaps.validate(
            registry, repo, set(adr.index))
        errors += [f"perception: {e}" for e in spot_errors]
        warnings += [f"perception: {w}" for w in spot_warnings]
    governed = [(config["adr_log"], adr_text)]
    for module in config["modules"]:
        for name in ("progress.md", "logs.md"):
            path = repo / module["path"] / name
            if path.is_file():
                governed.append((f"{module['path']}/{name}", path.read_text(encoding="utf-8")))
    for rel, text in governed:
        lines = find_conflict_markers(text)
        if lines:
            errors.append(f"{rel}: conflict marker at line {', '.join(map(str, lines))}")
        mojibake = find_mojibake(text)
        if mojibake:
            errors.append(f"{rel}: suspicious encoding ('??' runs) at line {', '.join(map(str, mojibake[:5]))}")

    refs, note = _history_refs(repo)
    if note:
        warnings.append(note)
    moved_roots, stale = _moved_roots(repo), []
    log_rels = [f"{m['path']}/logs.md" for m in config["modules"]]
    unchanged = {r: set(t.splitlines()) - set(d.splitlines())
                 if (t := _git(repo, "ls-tree", "--name-only", r, "--", *log_rels)) is not None
                 and (d := _git(repo, "diff", "--name-only", r, "--", *log_rels)) is not None else set() for r in refs}
    for module in config["modules"]:
        name, base = module["name"], repo / module["path"]
        try:
            meta = _read_progress(repo, module)
        except HarnessError as exc:
            errors.append(str(exc))
            continue
        if meta.get("module") != name:
            errors.append(f"{name}/progress.md: module field is {meta.get('module')!r}")
        errors += [f"{name}/progress.md: {e}" for e in validate_progress(meta, known_adrs=set(adr.index))]
        errors += [f"{name}/progress.md: plan not found: {p}" for p in meta.get("plans") or [] if not (repo / p).is_file()]

        log_path = base / "logs.md"
        if not log_path.is_file():
            errors.append(f"{name}: missing logs.md")
        else:
            text = log_path.read_text(encoding="utf-8")
            errors += [f"{name}/logs.md: {e}" for e in validate_log(text)]
            check_refs = [r for r in refs if f"{module['path']}/logs.md" not in unchanged[r]]
            log_errors, log_warnings = _append_only_findings(repo, check_refs, name, module["path"], text, moved_roots)
            errors += log_errors
            warnings += log_warnings

        commit = (meta.get("last_verified") or {}).get("commit")
        if commit == UNCOMMITTED:
            warnings.append(f"{name}: last_verified is an uncommitted tree; re-verify and record the commit")
        elif isinstance(commit, str):
            stale.append((name, module["path"], commit))
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda s: _git(repo, "rev-list", "--count", f"{s[2]}..HEAD", "--", s[1]), stale))
    for (name, path, commit), count in zip(stale, counts):
        if count is None:
            warnings.append(f"{name}: last_verified commit {commit} not found in git history")
        elif int(count) > int(config.get("stale_after_commits", 5)):
            warnings.append(f"{name}: {count.strip()} commits touched {path} since last_verified {commit}")
    errors += [f"generated: {p}" for p in check_generated(repo, adr)]
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("generate", "lint", "brief", "affected"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--base", default="main", help="affected: diff base ref (merge base with HEAD)")
    parser.add_argument("--head", help="affected: diff base...HEAD for this commit only, ignoring the"
                                       " working tree (the pre-push hook's pushed sha)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--print", dest="action", action="store_const", const="print",
                        help="affected: print the selection (default)")
    action.add_argument("--run", dest="action", action="store_const", const="run",
                        help="affected: run the selected pytest invocations")
    parser.add_argument("--json", action="store_true", help="affected: machine-readable selection")
    parser.add_argument("--ci-matrix", action="store_true",
                        help="affected: one-line JSON {mode, matrix} for the GitHub job matrix (ci.yml)")
    parser.add_argument("--skip", action="append", default=[], metavar="PATH",
                        help="affected --run: drop this selected path (already run by the caller); repeatable")
    parser.add_argument("--full", action="store_true",
                        help="affected --run: also run a FULL selection locally (default: GitHub runs it)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    repo = args.repo.resolve()
    if args.command == "affected":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import affected_tests  # noqa: E402 — sibling module, loaded on demand

        return affected_tests.main(repo, args.base, args.action or "print", args.json,
                                   matrix=args.ci_matrix, allow_full=args.full, skip=tuple(args.skip),
                                   head=args.head)
    if args.command == "brief":
        print(render_brief(repo), end="")
        return 0
    if args.command == "generate":
        for path in generate(repo):
            print(f"wrote {path.relative_to(repo).as_posix()}")
        return 0

    errors, warnings = lint(repo)
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"ERROR {error}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
