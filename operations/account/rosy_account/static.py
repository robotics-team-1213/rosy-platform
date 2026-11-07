"""Serve only the existing Account pages and their declared assets."""
import json
from pathlib import Path

PAGES = frozenset(('/console/login', '/console/profile', '/console/accounts'))
ASSETS = frozenset(('fleet-document.css', 'password-login.css', 'password-login.js', 'login-page.js',
                    'login-return.js', 'profile-page.js', 'account-page.js', 'account-permissions.js'))
CSP = "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"


def install_static(app, web_root, web_common):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
    root, common = Path(web_root).resolve(), Path(web_common).resolve()
    registry = json.loads((root / 'assets.json').read_text(encoding='utf-8'))
    common_assets = json.loads((common / 'shared-assets.json').read_text(encoding='utf-8'))['shared_assets']

    def serve(base, entry, *, account_page=False):
        path = (base / entry['path']).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(404)
        headers = {'Cache-Control': 'no-cache', 'Content-Security-Policy': CSP}
        if account_page:
            text = path.read_text(encoding='utf-8')
            text = text.replace('<html ', '<html data-app="account" ', 1)
            text = text.replace('<title>Rosy Fleet —', '<title>Rosy Account —', 1)
            text = text.replace('<b>Rosy Fleet</b>', '<b>Rosy Account</b>', 1)
            text = text.replace('href="/common/icons/console.svg"', 'href="/common/brand/mark.svg"', 1)
            text = text.replace('계정 로그인', 'Rosy Account 로그인')
            # /console only redirects to the profile on this origin; Fleet stays open in its own tab.
            text = text.replace('<ui-brand href="/console">', '<ui-brand href="/console/profile">', 1)
            text = text.replace('<a href="/console">관제로 돌아가기</a> · ', '', 1)
            return HTMLResponse(text, headers=headers)
        return FileResponse(path, media_type=entry['media_type'], headers=headers)

    def page_handler(url):
        def page():
            return serve(root, registry['pages'][url], account_page=True)
        return page

    for url in PAGES:
        app.add_api_route(url, page_handler(url), methods=['GET'], include_in_schema=False)

    @app.get('/console/assets/{name:path}', include_in_schema=False)
    def asset(name: str):
        if name not in ASSETS or name not in registry['assets']:
            raise HTTPException(404)
        return serve(root, registry['assets'][name])

    @app.get('/common/{name:path}', include_in_schema=False)
    def shared(name: str):
        if name not in common_assets:
            raise HTTPException(404)
        return serve(common, {'path': name, 'media_type': common_assets[name]})

    @app.get('/console', include_in_schema=False)
    @app.get('/', include_in_schema=False)
    def home():
        return RedirectResponse('/console/profile', status_code=303)
