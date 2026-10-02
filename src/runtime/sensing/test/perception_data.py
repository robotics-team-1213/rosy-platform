"""Locate the gitignored real-drive data (data/perception, D-379) for regression tests.

Order: $ROSY_PERCEPTION_DATA, this checkout, then the main checkout behind a linked
worktree. A test that needs it skips with a loud REAL-DATA CHECK NOT RUN reason."""
import os
import pathlib

import pytest

SESSION_133221Z = '20260930T133221Z_rosy-pinky-8kcn'


def root():
    repo = pathlib.Path(__file__).resolve().parents[4]
    roots = [repo / 'data' / 'perception']
    dot_git = repo / '.git'
    if dot_git.is_file():
        gitdir = (repo / dot_git.read_text().split(':', 1)[1].strip()).resolve()
        roots.append(gitdir.parents[1].parent / 'data' / 'perception')
    if os.environ.get('ROSY_PERCEPTION_DATA'):
        roots.insert(0, pathlib.Path(os.environ['ROSY_PERCEPTION_DATA']))
    return next((r for r in roots if r.is_dir()), None)


def label_file(session, kind, index):
    """labels/<session>/<kind>/<index>.<jpg|png>, or a loud skip when absent."""
    base = root()
    ext = 'jpg' if kind == 'frames' else 'png'
    path = None if base is None else base / 'labels' / session / kind / f'{index:06d}.{ext}'
    if path is None or not path.is_file():
        pytest.skip(f'REAL-DATA CHECK NOT RUN: {session}/{kind}/{index:06d} not found '
                    '(gitignored data/perception; set ROSY_PERCEPTION_DATA)')
    return path
