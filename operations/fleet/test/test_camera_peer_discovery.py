import importlib.util
from pathlib import Path
import pytest
from core_common.protocol.discovery_txt import classify,Accepted,Rejected

SITE = Path(__file__).resolve().parents[3]/'deploy/site'


def module(name):
    spec=importlib.util.spec_from_file_location(name,SITE/(name+'.py'))
    loaded=importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded); return loaded


def test_camera_peer_hint_is_additive_and_requires_existing_pairing():
    publisher=module('fleet-mdns')
    old=publisher.render_service(8443,role='overhead',tls_host='site.local',pair=True)
    new=publisher.render_service(8443,role='overhead',tls_host='site.local',pair=True,camera_peer=True)
    assert 'pair=rosy-pair/1' in old and 'peer=rosy.camera-peer/1' not in old
    assert 'pair=rosy-pair/1' in new and 'peer=rosy.camera-peer/1' in new
    with pytest.raises(ValueError):
        publisher.render_service(8443,role='overhead',tls_host='site.local',camera_peer=True)


@pytest.mark.parametrize('profile,pair,accepted', [('rosy.camera-peer/1','rosy-pair/1',True),
    ('unknown','rosy-pair/1',False),('rosy.camera-peer/1',None,False)])
def test_optional_discovery_profile_never_crosses_role_or_trust_boundary(profile,pair,accepted):
    txt=[('product','rosy'),('role','overhead-camera'),('proto','rosy-overhead/1'),('tls','required'),
         ('tls_host','site.local'),('peer',profile)]
    if pair:txt.append(('pair',pair))
    result=classify('_rosy-overhead._tcp','site.local','192.168.1.2',8443,txt)
    assert isinstance(result,Accepted if accepted else Rejected)


def config():
    flags=['--pairing-ca','--pairing-tls-host','--tls-cert','--tls-key','--users-file','--tasks-db','--pairing-sync-token-env']
    return {'services':{'proxy':{'ports':[{'target':8443,'published':8443,'host_ip':'127.0.0.1'}]},
            'fleet':{'command':[word for flag in flags for word in (flag,'configured-value')]}},
            'x-rosy-site':{'camera_peer_profile':'rosy.camera-peer/1'}}


def test_resolved_compose_declares_complete_owner_configuration_before_hint(tmp_path):
    firewall=module('site-firewall'); settings=firewall.compose_settings(config())
    assert settings['camera_peer']=='1'
    # write_public_env cannot turn legacy-disabled pairing into peer capability.
    settings.update(pairing='0'); output=tmp_path/'public.env'
    firewall.write_public_env(settings,output)
    assert 'ROSY_SITE_CAMERA_PEER=0' in output.read_text()
    settings['pairing']='1'; firewall.write_public_env(settings,output)
    assert 'ROSY_SITE_CAMERA_PEER=1' in output.read_text()
    malformed=config(); malformed['services']['fleet']['command'].remove('--users-file')
    with pytest.raises(firewall.ConfigError):firewall.compose_settings(malformed)
