"""Static review assets; the review handler authenticates requests before dispatch."""
import json
from pathlib import Path

STATIC = Path(__file__).with_name('review_app_web')
COMMON = Path(__file__).resolve().parents[3] / 'shared/web'
SHARED_ASSETS = json.loads((COMMON / 'shared-assets.json').read_text(encoding='utf-8'))['shared_assets']


def get(handler, path):
    files = {'/': 'index.html', '/app.js': 'app.js', '/history.js': 'history.js', '/viewport.js': 'viewport.js', '/commands.js': 'commands.js', '/app.css': 'app.css',
             '/classes': 'classes.html', '/classes.js': 'classes.js',
             '/review-pages.js': 'review-pages.js', '/review-context.js': 'review-context.js', '/box-geometry.mjs': 'box-geometry.mjs', '/learning': 'learning.html',
             '/learning.js': 'learning.js', '/pixels': 'pixels.html', '/pixels.js': 'pixels.js',
             '/storage.js': 'storage.js', '/storage-settings.js': 'storage-settings.js', '/versions.js': 'versions.js', '/ai-jobs.js': 'ai-jobs.js',
             '/catalog': 'catalog.html', '/catalog.js': 'catalog.js',
             '/accounts': 'accounts.html', '/accounts.js': 'accounts.js', '/account-session.js':'account-session.js',
             '/learning/evaluate': 'evaluate.html', '/evaluate.js': 'evaluate.js',
             '/learning/workspaces': 'workspaces.html', '/workspaces.js': 'workspaces.js'}
    name = path.removeprefix('/common/')
    if path in {'/file-picker.css', '/file-picker.js'}:
        file = COMMON.parents[1] / 'applications/fleet/web/shared' / path[1:]
        mime = 'text/css' if file.suffix == '.css' else 'text/javascript'
        handler.send(file.read_bytes(), mime=mime + '; charset=utf-8')
        return True
    if path.startswith('/common/') and name in SHARED_ASSETS:
        file = COMMON / name
        handler.send(file.read_bytes(), mime=SHARED_ASSETS[name])
        return True
    if path in files:
        file = STATIC / files[path]
        types = {'.html': 'text/html', '.css': 'text/css',
                 '.js': 'text/javascript', '.mjs': 'text/javascript'}
        handler.send(file.read_bytes(), mime=types[file.suffix] + '; charset=utf-8')
        return True
    return False
