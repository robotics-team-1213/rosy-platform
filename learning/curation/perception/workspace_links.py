"""--workspace-links: the center's other review workspaces, shown as links only (D-857 §2)."""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit


WORKSPACE_LINKS_SCHEMA = 'rosy.learning.workspace-links/1'
WORKSPACE_KINDS = ('training', 'evaluation', 'review')


def check_workspace_links(value):
    """The center's other review workspaces (D-857 §2): separate states, shown as links only (D-485)."""
    if not isinstance(value, dict) or set(value) != {'schema', 'workspaces'} or value['schema'] != WORKSPACE_LINKS_SCHEMA:
        raise ValueError(f'schema must be {WORKSPACE_LINKS_SCHEMA} with only schema and workspaces')
    rows = value['workspaces']
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError('workspaces must be a list of at most 20 entries')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not {'id', 'label', 'url', 'kind'} <= set(row) <= {'id', 'label', 'url', 'kind', 'note'}
                or not all(isinstance(v, str) for v in row.values())):
            raise ValueError('each workspace needs string id, label, url, kind and an optional note')
        if not re.fullmatch(r'[a-z0-9-]{1,40}', row['id']) or row['id'] in seen:
            raise ValueError(f'workspace id {row["id"]!r} must be unique [a-z0-9-]{{1,40}}')
        seen.add(row['id'])
        if not row['label'].strip() or len(row['label']) > 60 or len(row.get('note', '')) > 160:
            raise ValueError(f'workspace {row["id"]}: label 1-60 and note at most 160 characters')
        if row['kind'] not in WORKSPACE_KINDS:
            raise ValueError(f'workspace {row["id"]}: kind must be one of {", ".join(WORKSPACE_KINDS)}')
        url = row['url']
        parts = urlsplit(url)
        try:
            parts.port
        except ValueError:
            parts = None
        if (parts is None or parts.scheme not in ('http', 'https') or not parts.hostname or '@' in parts.netloc
                or '#' in url or len(url) > 300 or any(c.isspace() or not c.isprintable() for c in url)):
            raise ValueError(f'workspace {row["id"]}: url must be http(s) with a host, no credentials or fragment, at most 300 characters')
    return rows


def load_workspace_links(path):
    """--workspace-links: a private regular file (not a link) of at most 64 KiB beside the state."""
    if Path(path).is_symlink():
        raise ValueError('--workspace-links must be a regular file, not a link')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('--workspace-links must be a regular file, not a link')
        raw = os.read(fd, 64 * 1024 + 1)  # a regular file returns up to EOF in one read
    finally:
        os.close(fd)
    if len(raw) > 64 * 1024:
        raise ValueError('--workspace-links is larger than 64 KiB')
    try:
        value = json.loads(raw.decode('utf-8'))
    except UnicodeDecodeError:
        raise ValueError('--workspace-links must be UTF-8 JSON') from None
    return check_workspace_links(value)
