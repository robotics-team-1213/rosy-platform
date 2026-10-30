"""Compile Learning's fixed shell slots into static pages; --check rejects drift."""
import argparse
from pathlib import Path
import re

PAGES = {'learning.html': ('home', 'page'), 'catalog.html': ('catalog', 'page'),
         'index.html': ('review', 'page'), 'tasks.html': ('tasks', 'page'),
         'evaluate.html': ('evaluate', 'page'), 'accounts.html': (None, None),
         'camera.html': ('catalog', 'true'), 'workspaces.html': ('catalog', 'true'),
         'omx.html': ('review', 'true'), 'pixels.html': ('review', 'true'),
         'vlm.html': ('review', 'true'), 'sim.html': ('tasks', 'true')}


def render(root, name):
    if name not in PAGES:
        raise ValueError('unknown Learning document')
    root = Path(root)
    document = (root / name).read_text(encoding='utf-8')
    for component in ('header', 'rail'):
        start, end = f'<!-- review:{component}:start -->', f'<!-- review:{component}:end -->'
        if document.count(start) != 1 or document.count(end) != 1:
            raise ValueError(f'{name}: missing or duplicate {component} slot')
        pattern = re.compile(re.escape(start) + r'.*?' + re.escape(end), re.S)
        if len(pattern.findall(document)) != 1:
            raise ValueError(f'{name}: malformed {component} slot')
        fragment = (root / 'components' / f'{component}.html.inc').read_text(encoding='utf-8').strip()
        for key in ('home', 'catalog', 'review', 'tasks', 'evaluate', 'account'):
            current = None
            if key == 'account' and name == 'accounts.html':
                current = 'page'
            elif key == PAGES[name][0]:
                current = PAGES[name][1]
            fragment = fragment.replace('{{' + key + '}}', f' aria-current="{current}"' if current else '')
        if '{{' in fragment or '<!-- review:' in fragment:
            raise ValueError('unresolved or nested Learning shell component')
        document = pattern.sub(lambda _: start + '\n' + fragment + '\n' + end, document)
    return document


def check(root):
    return [name for name in PAGES if render(root, name) != (Path(root) / name).read_text(encoding='utf-8')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).with_name('review_app_web')
    if args.check:
        stale = check(root)
        if stale:
            parser.exit(1, 'Stale Learning shell: ' + ', '.join(stale) + '\n')
    else:
        for name in PAGES:
            (root / name).write_text(render(root, name), encoding='utf-8')


if __name__ == '__main__':
    main()
