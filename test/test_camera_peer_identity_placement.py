"""D226 private application identity isolation, with public trust material visible."""
from pathlib import Path
import subprocess
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def placement_repo(tmp_path):
    # Isolated X pytest scratch only: never mutate the product git index or refs.
    subprocess.run(['git','init','--quiet',str(tmp_path)],check=True)
    (tmp_path/'.gitignore').write_text((ROOT/'.gitignore').read_text(encoding='utf-8'),encoding='utf-8')
    return tmp_path


@pytest.mark.parametrize('name',['fleet.sqlite3.camera-peer.pem','nested/site.db.camera-peer.pem'])
def test_generated_private_identity_is_ignored(placement_repo,name):
    result=subprocess.run(['git','-c','core.excludesFile=','check-ignore','--no-index',name],
                          cwd=placement_repo,capture_output=True,text=True)
    assert result.returncode == 0 and result.stdout.strip() == name


@pytest.mark.parametrize('name',['site-ca.pem','nested/site-leaf.pem','camera-peer-identity.template.yaml'])
def test_public_ca_leaf_and_placement_template_remain_visible(placement_repo,name):
    result=subprocess.run(['git','-c','core.excludesFile=','check-ignore','--no-index',name],
                          cwd=placement_repo,capture_output=True,text=True)
    assert result.returncode == 1 and not result.stdout


def test_public_template_declares_ownership_without_private_key_material():
    path=ROOT/'deploy/site/camera-peer-identity.template.yaml'
    raw=path.read_text(encoding='utf-8'); data=yaml.safe_load(raw)
    assert data['profile'] == 'rosy.camera-peer/1'
    assert data['private_identity']['path_rule'] == '<tasks-db>.camera-peer.pem'
    assert data['private_identity']['mode'] == '0600'
    assert data['public_identity']['fields'] == ['receiver_id','receiver_public_key','receiver_key_sha256']
    assert '-----BEGIN' not in raw and 'token:' not in raw
