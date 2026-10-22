"""Curation outputs stay outside resolved source working trees."""
from pathlib import Path


def in_source_checkout(path) -> bool:
    path = Path(path).resolve()
    return any((parent / '.git').exists() for parent in (path, *path.parents))
