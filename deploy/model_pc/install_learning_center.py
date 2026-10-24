"""Preview or install an isolated, commit-pinned loopback Learning candidate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess


SERVICE = 'rosy-learning-center.service'
APP = Path('learning/curation/perception/review_app.py')
INSTALLER = Path('deploy/model_pc/install_learning_center.py')


def absolute(raw: str | Path, *, interpreter: bool = False) -> Path:
    path = Path(raw)
    if not path.is_absolute() or any(c in str(path) for c in '\r\n\x00%$"\\'):
        raise ValueError('paths must be absolute and contain no systemd substitutions or escapes')
    if path.is_symlink() and not interpreter:
        raise ValueError('paths must not be symbolic links')
    # Resolving a venv's Python symlink would silently run the system environment.
    return path if interpreter else path.resolve()


def git(source: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(source), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def quoted(path: Path | str) -> str:
    return '"' + str(path) + '"'


def collaboration_config(raw, roots):
    if raw is None:
        return None
    config = absolute(raw)
    if not config.is_file() or any(root == config or root in config.parents for root in roots):
        raise ValueError('private collaboration configuration must stay outside source and learning data')
    if os.name == 'posix' and (config.stat().st_mode & 0o077 or config.stat().st_uid != os.getuid()):
        raise ValueError('collaboration configuration requires owner-only permissions')
    document = json.loads(config.read_text(encoding='utf-8'))
    if (not isinstance(document, dict) or not isinstance(document.get('project_id'), str)
            or not document['project_id'].strip() or document['project_id'] != document['project_id'].strip()):
        raise ValueError('explicit collaboration project identity required')
    for key in ('accounts_db', 'key_file', 'imports_root', 'account_client_file'):
        if key == 'account_client_file' and not document.get(key):
            continue
        if key not in document:
            raise ValueError('private account storage paths required')
        path = absolute(document[key])
        if any(root == path or root in path.parents or path in root.parents for root in roots):
            raise ValueError('account storage must stay separate from source and learning data')
    for database, table, column in [(roots[1]/'reviews.sqlite3', 'metadata', 'value'),
                                    (roots[2]/'center.sqlite', 'workspace_binding', 'project_id')]:
        if not database.exists():
            continue
        try:
            with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as db:
                if not db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone():
                    continue
                query = ('SELECT value FROM metadata WHERE key="collaboration_project"' if table == 'metadata'
                         else 'SELECT project_id FROM workspace_binding WHERE singleton=1')
                row = db.execute(query).fetchone()
                if row and row[0] != document['project_id']:
                    raise ValueError('collaboration project differs from existing workspace binding')
        except sqlite3.Error as exc:
            raise ValueError('existing account project binding could not be verified') from exc
    return config


def prepare(args: argparse.Namespace) -> tuple[str, tuple[Path, Path]]:
    source, state, config = [absolute(p) for p in
                             (args.source_root, args.state, args.center_config)]
    python = absolute(args.python, interpreter=True)
    if not re.fullmatch('[0-9a-f]{40}', args.commit):
        raise ValueError('--commit must be a full lowercase Git SHA')
    if not 1024 <= args.port <= 65535:
        raise ValueError('--port must be between 1024 and 65535')
    if git(source, 'rev-parse', '--show-toplevel') != str(source):
        raise ValueError('--source-root must be the checkout root')
    if git(source, 'rev-parse', 'HEAD') != args.commit or git(source, 'status', '--porcelain'):
        raise ValueError('source must be clean at the exact approved commit')
    for required in (APP, INSTALLER):
        if not (source / required).is_file():
            raise ValueError(f'source missing {required}')
    data = json.loads(config.read_text(encoding='utf-8'))
    if data.get('schema') != 'rosy.omx.center-config/1':
        raise ValueError('unsupported center configuration schema')
    center = absolute(data['root'])
    if set(data.get('python', {})) != {'act', 'hilserl'}:
        raise ValueError('center configuration requires act and hilserl Python paths')
    for executable in (python, *(absolute(p, interpreter=True) for p in data['python'].values())):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError('configured Python must be an executable file')
    roots = (source, state, center)
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise ValueError('source, review state and center root must be separate')
    if any(root == config or root in config.parents for root in (state, center)):
        raise ValueError('center configuration must be outside mutable state')
    collaboration = collaboration_config(getattr(args, 'collaboration', None), roots)
    check = [python, source / INSTALLER, '--source-root', source, '--commit', args.commit,
             '--state', state, '--center-config', config, '--python', python, '--port', str(args.port)]
    start = [python, source / APP, '--state', state,
             '--omx-center-config', config, '--host', '127.0.0.1', '--port', str(args.port)]
    if collaboration is not None:
        check.extend(['--collaboration', collaboration])
        start.extend(['--collaboration', collaboration])
    unit = '\n'.join([
        '[Unit]', 'Description=ROSY isolated Learning center candidate', '', '[Service]',
        'Type=simple', f'WorkingDirectory={source}',
        'ExecStartPre=' + ' '.join(quoted(p) for p in check),
        'ExecStart=' + ' '.join(quoted(p) for p in start),
        'Environment=PYTHONDONTWRITEBYTECODE=1', 'NoNewPrivileges=yes', 'PrivateTmp=yes',
        'UMask=0077', 'Restart=on-failure', '', '[Install]', 'WantedBy=default.target', '',
    ])
    return unit, (state, center)


def install(args: argparse.Namespace, *, home: Path | None = None) -> str:
    unit, roots = prepare(args)
    unit_path = (home or Path.home()) / '.config/systemd/user' / SERVICE
    if unit_path.is_symlink() or (unit_path.exists() and unit_path.read_text(encoding='utf-8') != unit):
        raise ValueError('refusing to overwrite a conflicting Learning center unit')
    existing = unit_path.exists()
    for root in roots:
        if root.exists():
            if not existing or not root.is_dir() or root.stat().st_uid != os.getuid():
                raise ValueError('state roots must be new, or owned by this identical installation')
    if args.apply:
        for root in roots:
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        if not existing:
            subprocess.run([str(args.python), str(args.source_root / APP), '--state', str(args.state),
                            '--empty-training', '--init-only'], check=True)
            with unit_path.open('x', encoding='utf-8') as stream:
                stream.write(unit)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'enable', '--now', SERVICE], check=True)
    return unit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('source-root', 'state', 'center-config', 'python'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--collaboration', type=Path, help='private existing project account and Hugging Face configuration')
    parser.add_argument('--apply', action='store_true', help='create isolated roots and enable the fixed user unit')
    args = parser.parse_args()
    try:
        print(install(args), end='')
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'error: {exc}\n')


if __name__ == '__main__':
    main()
