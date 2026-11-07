"""D-992: Fleet's one narrow write: this robot's registry row. Machine credentials stay out of Account."""
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from rosy_account.account_authority import NO_STORE
from rosy_account.client_registry import public, validate_client

CALLBACK_PATH = '/api/account/callback'
ROBOT = re.compile(r'[A-Za-z0-9._-]{1,90}')


def register_device(authority, robot_id, *, callback, home_url, label, clock):
    """Address and label only: an administrator's stop survives re-registration (D-992 3)."""
    client_id = f'robot-{robot_id}'
    resources = [f'robot:{robot_id}']
    validate_client(client_id, [callback], resources, label, home_url)
    if urlsplit(callback).path != CALLBACK_PATH:
        raise ValueError('device callback must be the CORE Account callback')
    with authority.transaction() as db:
        row = db.execute('SELECT * FROM account_clients WHERE client_id=?', (client_id,)).fetchone()
        if row is None:
            db.execute('INSERT INTO account_clients VALUES (?,?,?,?,?,1,1)',
                       (client_id, json.dumps([callback]), json.dumps(resources), label, home_url))
            before = None
        else:
            before = public(row)
            if before['resources'] != resources:
                raise PermissionError('that client is not this robot')
            if (before['redirect_uris'], before['label'], before['home_url']) == ([callback], label, home_url):
                return before
            db.execute('UPDATE account_clients SET redirect_uris=?,label=?,home_url=?,revision=? WHERE client_id=?',
                       (json.dumps([callback]), label, home_url, before['revision'] + 1, client_id))
        after = public(db.execute('SELECT * FROM account_clients WHERE client_id=?', (client_id,)).fetchone())
        db.execute('INSERT INTO account_client_audit VALUES (?,?,?,?,?,?,?,?)', (
            'device-registrar', client_id, 'device-register', before['revision'] if before else 0, after['revision'],
            clock(), json.dumps(before or {}), json.dumps(after)))
        return after


def install_device_client_routes(app, authority, *, registrar_token_sha256, clock):
    @app.put('/api/fleet/auth/device-clients/{robot_id}', include_in_schema=False)
    async def device_client(robot_id: str, request: Request, payload: dict = Body(...)):
        values = request.headers.getlist('authorization')
        supplied = values[0][7:] if len(values) == 1 and values[0].startswith('Bearer ') else ''
        digest = hashlib.sha256(supplied.encode('utf-8')).hexdigest()
        if not registrar_token_sha256 or not hmac.compare_digest(digest, registrar_token_sha256):
            raise HTTPException(403, detail={'code': 'REGISTRAR_REQUIRED'}, headers=NO_STORE)
        if not ROBOT.fullmatch(robot_id) or set(payload) != {'callback', 'home_url', 'label'}:
            raise HTTPException(422, detail={'code': 'INVALID_REQUEST'}, headers=NO_STORE)
        try:
            row = await run_in_threadpool(register_device, authority, robot_id, clock=clock, **payload)
        except PermissionError:
            raise HTTPException(409, detail={'code': 'CLIENT_NOT_THIS_ROBOT'}, headers=NO_STORE) from None
        except ValueError:
            raise HTTPException(422, detail={'code': 'INVALID_REQUEST'}, headers=NO_STORE) from None
        return JSONResponse(row, headers=NO_STORE)
