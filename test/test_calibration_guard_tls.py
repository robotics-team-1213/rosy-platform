"""Actual local TLS calibration receiver; no device operations."""
import datetime
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
ROOT=Path(__file__).resolve().parents[1]
GUARD=ROOT/'deploy/robot/pinky_pro/rosy-calibration-guard.ps1'
PS=shutil.which('powershell') or shutil.which('pwsh')
TOKEN='calibration-synthetic-token'
pytestmark=pytest.mark.skipif(not PS,reason='PowerShell required')

@pytest.fixture
def receiver(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'core.test')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
          .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True)
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('core.test')]),False).sign(key,hashes.SHA256()))
    ca=tmp_path/'ca.pem';ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private=tmp_path/'key.pem';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    state={'auth':[],'body':{'session':None},'status':200,'delay':0}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            import time
            state['auth'].append(self.headers.get('Authorization'))
            assert self.path=='/api/v1/calibration/session'
            time.sleep(state['delay'])
            body=state.get('raw',json.dumps(state['body']).encode())
            self.send_response(state['status']);self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ssl.SSLError):pass
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(ca,private)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    state.update(port=server.server_port,ca=ca)
    yield state
    server.shutdown();server.server_close()

def invoke(receiver,tmp_path,*extra,token=True):
    env=dict(os.environ);env.pop('ROSY_API_TOKEN',None);env['LOCALAPPDATA']=str(tmp_path)
    if token:env['ROSY_API_TOKEN']=TOKEN
    args=[PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(GUARD),'-Robot','127.0.0.1',
          '-ApiPort',str(receiver['port']),'-ApiTlsHost','core.test','-ApiCaFile',str(receiver['ca']),
          '-SshExe','nonexistent-test-ssh','-TimeoutSec','1']
    pending=list(extra)
    for flag in ['-ApiCaFile','-ApiTlsHost']:
        if flag in pending:
            index=pending.index(flag);args[args.index(flag)+1]=pending[index+1];del pending[index:index+2]
    args.extend(pending)
    result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=20)
    assert TOKEN not in result.stdout+result.stderr
    return result

def test_secure_idle_and_active_force_policy(receiver,tmp_path):
    assert invoke(receiver,tmp_path).returncode==0
    receiver['body']={'session':{'id':'private-session-not-stdout','kind':'drive','label':'drive-cal',
                                'owner':{'id':'owner','role':'operator','label':'laptop'},'remaining_s':12}}
    refused=invoke(receiver,tmp_path)
    assert refused.returncode==3 and 'private-session-not-stdout' not in refused.stdout+refused.stderr
    assert invoke(receiver,tmp_path,'-Force').returncode==0
    assert receiver['auth']==['Bearer '+TOKEN]*3

@pytest.mark.parametrize('case',['wrong-ca','wrong-name','missing-token','unauthorized','forbidden','redirect','malformed','missing-session','timeout','oversize','duplicate-session','scalar-session'])
def test_secure_failure_closed(receiver,tmp_path,case):
    extra=[];token=True
    if case=='wrong-ca':
        other_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'unrelated-ca')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(other_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
              .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True)
              .sign(other_key,hashes.SHA256()))
        other=tmp_path/'other-ca.pem';other.write_bytes(cert.public_bytes(serialization.Encoding.PEM));extra=['-ApiCaFile',str(other)]
    elif case=='wrong-name':extra=['-ApiTlsHost','other.test']
    elif case=='missing-token':token=False
    elif case=='unauthorized':receiver['status']=401
    elif case=='forbidden':receiver['status']=403
    elif case=='redirect':receiver['status']=302
    elif case=='malformed':receiver['raw']=b'not json'
    elif case=='missing-session':receiver['body']={'anything':True}
    elif case=='timeout':receiver['delay']=2
    elif case=='oversize':receiver['raw']=b'x'*17000
    elif case=='duplicate-session':receiver['raw']=b'{"session":{},"session":null}'
    elif case=='scalar-session':receiver['body']={'session':False}
    result=invoke(receiver,tmp_path,*extra,'-Force',token=token)
    assert result.returncode==2,result.stdout+result.stderr
    if case in ('wrong-ca','wrong-name','missing-token'):assert receiver['auth']==[]


def test_release_caller_denies_secure_failure_before_remote(receiver,tmp_path):
    env=dict(os.environ);env['ROSY_API_TOKEN']=TOKEN;env['LOCALAPPDATA']=str(tmp_path)
    receiver['status']=401
    result=subprocess.run([PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(GUARD.parent/'rosy-release-push.ps1'),
                           '-Robot','127.0.0.1','-Rollback','-ApiPort',str(receiver['port']),
                           '-ApiTlsHost','core.test','-ApiCaFile',str(receiver['ca']),'-SshExe','nonexistent-test-ssh'],
                          env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode!=0 and 'calibration check failed' in (result.stdout+result.stderr).lower()
    assert '+ nonexistent-test-ssh' not in result.stdout+result.stderr


@pytest.mark.parametrize('flag',['-ApiCaFile','-ApiTlsHost'])
def test_partial_tls_parameters_refuse_before_any_request(receiver,tmp_path,flag):
    env=dict(os.environ);env['ROSY_API_TOKEN']=TOKEN
    value=str(receiver['ca']) if flag=='-ApiCaFile' else 'core.test'
    result=subprocess.run([PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(GUARD),
                           '-Robot','127.0.0.1','-ApiPort',str(receiver['port']),flag,value,'-Force'],
                          env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==2 and receiver['auth']==[]


def test_ca_filename_with_spaces_and_credential_echo_denial(receiver,tmp_path):
    spaced=tmp_path/'trusted CA.pem';spaced.write_bytes(receiver['ca'].read_bytes())
    assert invoke(receiver,tmp_path,'-ApiCaFile',str(spaced)).returncode==0
    receiver['body']={'session':{'kind':'drive','label':TOKEN,'owner':{'role':'operator','label':'laptop'},'remaining_s':1}}
    assert invoke(receiver,tmp_path).returncode==2


def test_dev_sync_denies_secure_failure_before_archive_or_upload(receiver,tmp_path):
    receiver['status']=403
    env=dict(os.environ);env['ROSY_API_TOKEN']=TOKEN;env['LOCALAPPDATA']=str(tmp_path);env['TEMP']=str(tmp_path)
    result=subprocess.run([PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(GUARD.parent/'dev/sync-core-dev.ps1'),
                           '-PiHost','127.0.0.1','-PiUser','rosy','-Backend','native','-ApiPort',str(receiver['port']),
                           '-ApiTlsHost','core.test','-ApiCaFile',str(receiver['ca'])],
                          env=env,capture_output=True,text=True,timeout=20,cwd=ROOT)
    assert result.returncode!=0 and 'calibration check failed' in (result.stdout+result.stderr).lower()
    assert not list(tmp_path.glob('rosy-dev-*'))
