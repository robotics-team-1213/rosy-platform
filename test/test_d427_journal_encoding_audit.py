"""The real damaged SIM AID journal may only become its UNKNOWN audit."""
from hashlib import sha256
from pathlib import Path
import subprocess

import pytest
import rosy_harness as harness

REPO = Path(__file__).resolve().parents[1]
SOURCE = '429e13b8313484a25751a7c7896fe1b7aca41b92'
HEADING = (
    '## 2026-10-04 ? uncommitted ? fix(g2): preserve the total SIM AI'
    'D deadline while allowing RPC acknowledgement'
)
AUDIT = (
    '## 2026-10-04 · uncommitted · audit(g2): SIM AID journal encodin'
    'g loss\n\n- Change: UNKNOWN. The original text was irreversibly en'
    'coded as question marks. No technical explanation has been recon'
    'structed. Original: `429e13b83134:deploy/logs.md`, normalized bl'
    'ock SHA256 `e2f80dbdfc41bdcff21a27d50ddd7ae909a32d02270c5db52580'
    '8c6d9977883d`.\n- Evidence: UNKNOWN. The exact original remains i'
    'n Git history and the local X audit evidence. This record proves'
    ' information loss; it does not establish the reported execution '
    'results.\n- Gate: UNKNOWN. No validation or acceptance promotion '
    'is authorized by this damaged record. Author-supplied original t'
    'ext and independent execution evidence remain required.'
)
OLD_SHA256 = 'e2f80dbdfc41bdcff21a27d50ddd7ae909a32d02270c5db525808c6d9977883d'


@pytest.fixture
def original():
    text = subprocess.check_output(
        ['git', 'show', SOURCE + ':deploy/logs.md'], cwd=REPO,
        text=True, encoding='utf-8',
    )
    return text[text.index(HEADING):].split('\n## ', 1)[0].strip()


def test_real_encoding_loss_can_only_become_unknown(original):
    assert sha256(original.encode()).hexdigest() == OLD_SHA256
    assert harness.find_mojibake(original)
    assert not harness.find_mojibake(AUDIT)
    assert harness.is_append_only(original, AUDIT)
    assert all(
        'UNKNOWN' in line for line in AUDIT.splitlines()
        if line.startswith('- ')
    )


@pytest.mark.parametrize(
    'mutation',
    ['old', 'audit', 'delete', 'peer-delete', 'peer-edit', 'future'],
)
def test_encoding_audit_rejects_other_changes(original, mutation):
    peer = '\n## 2026-10-04 · abcdef0 · preserved peer\n- Change: original'
    old, new = original, AUDIT
    if mutation == 'old':
        old += 'x'
    elif mutation == 'audit':
        new += 'x'
    elif mutation == 'delete':
        new = ''
    elif mutation == 'peer-delete':
        old += peer
    elif mutation == 'peer-edit':
        old += peer
        new += peer.replace('original', 'changed')
    else:
        old = old.replace('RPC acknowledgement', 'future RPC acknowledgement')
    assert not harness.is_append_only(old, new)


def test_audit_does_not_hide_new_corruption():
    assert harness.find_mojibake(AUDIT + '\n- Change: new ?? corruption')
