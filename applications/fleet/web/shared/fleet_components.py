"""Compile Fleet-owned chrome into static HTML; --check rejects generated drift."""
import argparse
from pathlib import Path
import re

PAGES = {'index.html': 'console', 'installation/install.html': 'install',
         'sitemap/site-map.html': 'map', 'cell/cell.html': 'work'}


def render(root, name):
    if name not in PAGES:
        raise ValueError('unknown Fleet document')
    root = Path(root)
    document = (root/name).read_text(encoding='utf-8')
    for component in ('header', 'nav'):
        start, end = f'<!-- fleet:{component}:start -->', f'<!-- fleet:{component}:end -->'
        if document.count(start) != 1 or document.count(end) != 1:
            raise ValueError(f'{name}: missing or duplicate {component} slot')
        pattern = re.compile(re.escape(start)+r'.*?'+re.escape(end), re.S)
        if len(pattern.findall(document)) != 1:
            raise ValueError(f'{name}: malformed {component} slot')
        fragment = (root/f'shared/fleet-{component}.html.inc').read_text(encoding='utf-8').strip()
        if component == 'nav':
            for key in ('console', 'work', 'records', 'map', 'install'):
                fragment = fragment.replace(' {{'+key+'}}', ' aria-current="page"' if key == PAGES[name] else '')
        if '{{' in fragment or '<!-- fleet:' in fragment:
            raise ValueError('unresolved or nested Fleet component')
        document = pattern.sub(lambda _: start+'\n'+fragment+'\n'+end, document)
    return document


def check(root):
    return [name for name in PAGES if render(root, name) != (Path(root)/name).read_text(encoding='utf-8')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.check:
        stale = check(root)
        if stale:
            parser.exit(1, 'Stale Fleet components: '+', '.join(stale)+'\n')
    else:
        for name in PAGES:
            (root/name).write_text(render(root, name), encoding='utf-8')


if __name__ == '__main__':
    main()
