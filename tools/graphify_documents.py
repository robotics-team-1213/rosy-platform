"""Add file inventory and explicit Markdown links from Graphify's filtered corpus."""
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

DEFINITION = re.compile(r'^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)')
LINK = re.compile(r'\[([^\]\n]+)\](?:\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)|\[([^\]\n]*)\])?')


def markdown_lines(text):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, re.sub(r'(`+).*?\1', '', line)


def augment(graph: dict, out: Path, scope: Path) -> dict:
    """Use only the freshly generated 0.9.91 corpus index; never rescan ignored files."""
    index = out / 'cache/stat-index.json'
    try:
        corpus = json.loads(index.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Missing or invalid Graphify corpus index') from exc
    if not isinstance(corpus, dict) or not corpus:
        raise ValueError('Missing or invalid Graphify corpus index')
    paths = {}
    for name in corpus:
        path = (scope / name).resolve()
        if not path.is_relative_to(scope):
            raise ValueError(f'Corpus path escapes scope: {name}')
        if not path.is_file():
            raise ValueError(f'Corpus file disappeared: {name}')
        paths[path] = path.relative_to(scope).as_posix()
    file_ids = {node['source_file']: node['id'] for node in graph['nodes']
                if node.get('source_file') and node.get('source_location') is None
                and node.get('label') in (node['source_file'], Path(node['source_file']).name)}
    ids = {path: file_ids.get(rel, 'inventory:' + rel) for path, rel in paths.items()}
    existing = {node['id'] for node in graph['nodes']}
    if any(ids[path] in existing for path, rel in paths.items() if rel not in file_ids):
        raise ValueError('Inventory node IDs collide with the extracted graph')
    for path, rel in paths.items():
        if rel in file_ids:
            continue
        graph['nodes'].append({'id': ids[path], 'label': rel, 'type': 'file', 'source_file': rel,
                               'source_location': 'L1', '_origin': 'structural'})
    edges = graph.setdefault('edges', graph.pop('links', []))
    coverage = {'indexed_files': len(paths), 'document_files': 0, 'document_links': 0,
                'unresolved_links': [], 'semantic_inference': False, 'multimedia_content_analysis': False}
    for source, rel in paths.items():
        if source.suffix.lower() not in ('.md', '.markdown'):
            continue
        coverage['document_files'] += 1
        lines = list(markdown_lines(source.read_text(encoding='utf-8', errors='replace')))
        definitions = {match[1].strip().casefold(): match[2] for _, line in lines
                       if (match := DEFINITION.match(line))}
        for number, line in lines:
            if DEFINITION.match(line):
                continue
            # shortcut: nested brackets/parentheses are not parsed; use a Markdown parser if needed.
            for match in LINK.finditer(line):
                href = match[2] or definitions.get((match[3] or match[1]).strip().casefold())
                if not href:
                    continue
                try:
                    url = urlsplit(href.strip('<>'))
                except ValueError:
                    continue
                if url.scheme or url.netloc or not url.path:
                    continue
                name = unquote(url.path).replace('\\', '/')
                target = (scope / name.lstrip('/') if name.startswith('/') else source.parent / name).resolve()
                if not target.is_relative_to(scope):
                    continue
                if target not in ids:
                    coverage['unresolved_links'].append({'source_file': rel, 'line': number,
                                                         'target': target.relative_to(scope).as_posix()})
                    continue
                edges.append({'source': ids[source], 'target': ids[target], 'relation': 'references',
                              'confidence': 'EXTRACTED', 'source_file': rel,
                              'source_location': f'L{number}', '_origin': 'structural'})
                coverage['document_links'] += 1
    return coverage
