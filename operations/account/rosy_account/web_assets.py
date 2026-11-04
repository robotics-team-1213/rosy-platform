"""Fixed Account UI bundle; frontend sources remain with their canonical owners."""
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import urljoin, urlsplit

from .static import ASSETS, PAGES

COMMON = ('tokens.css', 'app-shell.css', 'components.css', 'component-controls.css', 'theme.js', 'ui.js', 'ui-wiring.js',
          'confirmation.js', 'live-dialog-geometry.js', 'fleet-client.js', 'request.js',
          'account-profile.js', 'icons/console.svg', 'brand/mark.svg')


class _Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.urls.append(attrs['src'])
        if tag == 'link' and set(attrs.get('rel', '').split()) & {'stylesheet', 'icon'}:
            self.urls.append(attrs['href'])


def _source(owner, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError('Account asset path escapes its owner')
    source = (owner / relative).resolve(strict=True)
    if not source.is_relative_to(owner.resolve(strict=True)) or not source.is_file():
        raise ValueError('invalid Account asset source')
    return source


def _references(source):
    if source.suffix not in {'.html', '.js', '.css'}:
        return []
    text = source.read_text(encoding='utf-8')
    if source.suffix == '.html':
        parser = _Resources()
        parser.feed(text)
        return parser.urls
    if source.suffix == '.js':
        return re.findall(r'''\bimport\s+(?:[^;\n]*?\s+from\s*)?["']([^"']+)["']''', text)
    return re.findall(r'''url\(\s*["']?([^\s"')]+)["']?\s*\)''', text)


def build_web(repo: Path, output: Path):
    """Publish only the fixed pages and complete resource closure to a new directory."""
    repo, output = repo.resolve(strict=True), output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    console, common = repo / 'applications/fleet/web', repo / 'shared/web'
    registry = json.loads((console / 'assets.json').read_text(encoding='utf-8'))
    shared = json.loads((common / 'shared-assets.json').read_text(encoding='utf-8'))['shared_assets']
    reduced = {'pages': {name: registry['pages'][name] for name in sorted(PAGES)},
               'assets': {name: registry['assets'][name] for name in sorted(ASSETS)}}
    common_registry = {'shared_assets': {name: shared[name] for name in COMMON}}
    urls, sources = {}, {}
    for group, entries in reduced.items():
        for name, entry in entries.items():
            destination = 'console/' + entry['path']
            source = _source(console, entry['path'])
            sources[destination] = source
            urls[name if group == 'pages' else '/console/assets/' + name] = source
    for name in COMMON:
        sources['common/' + name] = _source(common, name)
        urls['/common/' + name] = sources['common/' + name]
    for url, source in urls.items():
        for reference in _references(source):
            parsed = urlsplit(reference)
            if parsed.scheme == 'data':
                continue
            target = urlsplit(urljoin(url, reference))
            if target.scheme or target.netloc or target.query or target.path not in urls:
                raise ValueError('Account resource references an asset outside its fixed bundle')
    with tempfile.TemporaryDirectory(prefix='.account-web-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'web'
        for name, source in sources.items():
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for name, document in (('console/assets.json', reduced), ('common/shared-assets.json', common_registry)):
            (stage / name).write_text(json.dumps(document, sort_keys=True) + '\n', encoding='utf-8')
        stage.rename(output)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build_web(args.repo, args.output)
