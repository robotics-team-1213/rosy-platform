"""The damaged SIM AID journal accepts only its exact reviewed source audit."""
from hashlib import sha256
from pathlib import Path
import subprocess

import pytest
import rosy_harness as harness

REPO = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = '429e13b8313484a25751a7c7896fe1b7aca41b92'
HEADING = (
    '## 2026-10-04 ? uncommitted ? fix(g2): preserve the total SIM AI'
    'D deadline while allowing RPC acknowledgement'
)
# The earlier UNKNOWN audit is historical; preserve the reviewed upstream repair.
AUDIT = '## 2026-10-04 · uncommitted · fix(g2): SIM AID 승인 응답의 전체 시간 한도 유지\n\n- 변경: 429e13b83의 SIM AID attach 요청 한도를 150ms로 조정하고 상태 echo 확인까지의 전체 200ms 한도를 유지한다. detach도 publish 시간을 포함해 남은 시간만 기다린다. transport 결과와 Boolean 응답을 따로 기록하며 한도를 넘긴 echo는 확인 성공으로 쓰지 않는다. 요청 재실행·stop 초기화·승인 확장은 없다.\n- 증거: 병합 원문의 인코딩 손상 항목은 X:/DevTemp/rosy-ui-ship/g2-aid-imported-journal-original.txt에 보존했다. 복구할 수 없는 실행 관측 문장은 현재 증거로 사용하지 않는다. 해당 source와 독립 host 검사를 대조하며 실제 ROS·장비 실행은 확인하지 않았다.\n- gate 변화: SOURCE/HOST 범위의 시간 한도 보완이다. 통합 G2 startup은 HOLD를 유지하며 box16·fault matrix·실제 startup·물리 수용은 HOLD/NOT_RUN이다. full_g2=false이며 자동 rearm이나 동작 제출은 하지 않는다.'
REPAIR_SHA256 = "d0cee132dfe7dc874ae52e59707f932d496f5b16c62975e8bf3733bacc891556"

OLD_SHA256 = 'e2f80dbdfc41bdcff21a27d50ddd7ae909a32d02270c5db525808c6d9977883d'


@pytest.fixture
def original():
    text = subprocess.check_output(
        ['git', 'show', SOURCE_COMMIT + ':deploy/logs.md'], cwd=REPO,
        text=True, encoding='utf-8',
    )
    return text[text.index(HEADING):].split('\n## ', 1)[0].strip()


def test_real_encoding_loss_accepts_only_exact_reviewed_repair(original):
    assert sha256(original.encode()).hexdigest() == OLD_SHA256
    assert harness.find_mojibake(original)
    assert not harness.find_mojibake(AUDIT)
    assert harness.is_append_only(original, AUDIT)
    assert sha256(AUDIT.encode()).hexdigest() == REPAIR_SHA256
    assert harness.KNOWN_LOG_ENCODING_REPAIRS[OLD_SHA256] == REPAIR_SHA256
    assert '복구할 수 없는 실행 관측 문장은 현재 증거로 사용하지 않는다' in AUDIT
    assert 'HOLD/NOT_RUN' in AUDIT
    assert 'full_g2=false' in AUDIT


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
