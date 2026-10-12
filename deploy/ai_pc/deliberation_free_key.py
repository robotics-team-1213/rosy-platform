"""Root import of only the existing OpenCode API key; no provider or budget operation."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile

SOURCE=Path('/home/ai/.local/share/opencode/auth.json')
TARGET=Path('/var/lib/rosy-deliberation/opencode-free.json')

def validate_parent(parent, info, uid, gid):
    if (parent.resolve()!=parent or not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in (0,uid) or info.st_gid!=gid
            or stat.S_IMODE(info.st_mode)!=0o750):
        raise ValueError('SECRET_PARENT_BOUNDARY_FAILED')


def existing_key(target, payload, uid, gid):
    try:
        info=target.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_gid!=gid
            or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>4096):
        raise ValueError('EXISTING_SELECTED_KEY_BOUNDARY_FAILED')
    fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        opened=os.fstat(fd)
        if (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino):
            raise ValueError('EXISTING_SELECTED_KEY_BOUNDARY_FAILED')
        saved=os.read(fd,4097)
    finally:
        os.close(fd)
    if saved!=payload:
        raise ValueError('EXISTING_SELECTED_KEY_DIFFERS')
    return True


def main():
    if os.geteuid()!=0: raise ValueError('ROOT_IMPORT_REQUIRED')
    from deploy.site.deliberation_install import validated_account
    account=validated_account(); owner=pwd.getpwnam('ai')
    fd=os.open(SOURCE,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner.pw_uid or info.st_mode&0o077 or info.st_size>1048576:
            raise ValueError('AUTH_SOURCE_BOUNDARY_FAILED')
        data=json.loads(os.read(fd,1048577))
    finally: os.close(fd)
    selected=data.get('opencode')
    if (type(selected) is not dict or selected.get('type')!='api' or type(selected.get('key')) is not str
            or not selected['key'] or any(ord(c)<33 or ord(c)>126 for c in selected['key'])):
        raise ValueError('SELECTED_OPENCODE_API_KEY_REQUIRED')
    payload=json.dumps({'type':'api','key':selected['key']},separators=(',',':')).encode()
    if len(payload)>4096: raise ValueError('KEY_SIZE_LIMIT')
    parent=TARGET.parent
    info=parent.lstat()
    validate_parent(parent,info,account.pw_uid,account.pw_gid)
    if existing_key(TARGET,payload,account.pw_uid,account.pw_gid):
        print(json.dumps({'state':'SELECTED_OPENCODE_ALREADY_MATCHES'}))
        return
    name=None
    try:
        fd,name=tempfile.mkstemp(prefix='.opencode-free-',dir=parent)
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600);os.fchown(stream.fileno(),account.pw_uid,account.pw_gid)
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        try:
            os.link(name,TARGET,follow_symlinks=False)
        except FileExistsError:
            existing_key(TARGET,payload,account.pw_uid,account.pw_gid)
        Path(name).unlink();name=None
        directory=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if name is not None: Path(name).unlink(missing_ok=True)
    print(json.dumps({'state':'IMPORTED_SELECTED_OPENCODE_ONLY','credential_sha256':hashlib.sha256(selected['key'].encode()).hexdigest()}))

if __name__=='__main__':
    try: main()
    except FileNotFoundError as error:
        print(json.dumps({'state':'HOLD','reason':'MISSING_PATH','path':str(error.filename)}));raise SystemExit(1)
    except ValueError as error:
        code=str(error)
        allowed={'DEDICATED_ACCOUNT_CONFLICT','ROOT_IMPORT_REQUIRED','AUTH_SOURCE_BOUNDARY_FAILED','SELECTED_OPENCODE_API_KEY_REQUIRED',
                 'KEY_SIZE_LIMIT','SECRET_PARENT_BOUNDARY_FAILED','EXISTING_SELECTED_KEY_BOUNDARY_FAILED',
                 'EXISTING_SELECTED_KEY_DIFFERS'}
        print(json.dumps({'state':'HOLD','reason':code if code in allowed else 'INVALID_AUTH_DATA'}));raise SystemExit(1)
    except Exception as error:
        print(json.dumps({'state':'HOLD','reason':type(error).__name__}));raise SystemExit(1)
