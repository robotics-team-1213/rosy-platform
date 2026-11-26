---
title: site 업데이트 체인 정지는 릴리스 제목이 아니라 감사 로그·hold 상태로 진단한다
date: 2026-11-03
category: deployment
module: deploy/site (auto_sign_candidates.py, rosy_site_autoupdate.py)
problem_type: operations_blindness
component: deployment
symptoms:
  - "gh release list 제목이 "(unsigned)"인데 자산에는 release.json.sig가 있다 (2026-10-29, 2026-10-31, 2026-11-03 재발)"
  - "서명 작업(RosySiteAutoSign)이 매 10분 exit 0인데 새 릴리스가 서명되지 않거나 사이트에 설치되지 않는다"
  - "사이트 journalctl에 15분마다 {"event": "held"}만 반복된다"
root_cause: silent_stoppage_on_two_layers
resolution_type: procedure
applies_when:
  - "사이트 릴리스가 오래 서명 안 됐거나 최신 서명 릴리스가 설치되지 않을 때"
  - "서명 PC 감사 로그(audit.jsonl)가 특정 태그에서 며칠 전에 끊겼을 때"
---

## Problem

"사이트가 최신을 안 따라온다"는 보고에 릴리스 목록부터 보면 진단이 꼬인다. 제목은 세 번이나
거짓말을 했고(서명됐는데 "(unsigned)"), 실제 정지 원인은 두 독립층 중 하나였다: (1) 서명 전 정지
— CI 빨강·서명 거부는 감사 로그에만 남는다(작업 exit 코드는 0/20으로 요약될 뿐), (2) 서명 후
정지 — 사이트 업데이터의 hold나 D-805 동결 관문은 어느 유닛도 실패로 만들지 않고 조용히 건너뛴다.

## Cause

- 릴리스 제목은 사람용 장식이며 서명 자산(`release.json.sig` 존재)이 정본이다. 제목 갱신은 서명
  흐름의 사후 단계라 서명만 별도로 붙으면 제목이 과거 상태에 남는다.
- `rosy_site_autoupdate.py hold`는 상태 파일과 `held` 저널 줄 외에 아무 표시를 내지 않는다.
  D-805 관문은 의도적으로 유닛을 실패로 표시하지 않는다(fail closed, silent skip).
- 서명 감사 로그(`<state_dir>/audit.jsonl`)는 의사결정마다 한 줄씩 남는 정본이다. 마지막 줄의
  시각·decision이 흐름이 끊긴 지점을 바로 알려준다.

## Solution

진단은 이 순서로, 각 층의 정본 신호만 본다:

1. 서명 PC: `<state_dir>/audit.jsonl` 마지막 줄들 — decision(`ci-red`, `refused`, `error`,
   `signed`)과 시각. `gh release list` 제목은 확인용이 아니다.
2. 사이트 호스트: `sudo python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py status`의
   `hold`, `failed`, `installed` + `journalctl -u rosy-site-autoupdate`의 `held`/`refused`.
3. 관문: `sudo /usr/local/bin/rosy-update-gate` 한 번 실행(0=실행, 1=건너뜀).

구조 예방(2026-11-03 착지, main 0656574fb674): 서명자가 (a) 서명 성공 뒤 `notify_hosts`에
SSH로 업데이터를 즉시 시작해 폴링 대기를 없애고, (b) 서명된 "(unsigned)" 제목을 스캔에서 발견하는
즉시 교정한다(`retitle-repaired`). hold·동결은 사람의 운영 결정이므로 자동으로 넘지 않는다 —
그래서 2번 상태 확인이 필수다.

## Verification

- 2026-11-03: 위 순서로 hold(D-960 fix pending)를 5분 내 진단, 검토된 main 도구 설치·resume로
  복구, `retitle-repaired` 2건 즉시 교정 확인. 시험 `test/test_site_auto_sign.py` 31통과.

## 추가 (2026-11-26): 일부 서비스만 돌리는 호스트와 증분 후보

증상: 셀(cell-a, fleet·vision·proxy만 운영)이 18:44부터 새 후보를 하나도 설치하지 않았다. 저널은
`held reused-image-missing-or-mismatched service=account`만 남기고 유닛은 성공으로 끝났다.

원인 세 겹:

1. 증분 후보(manifest v2)는 바뀌지 않은 서비스 이미지를 `reused_images`로 표시만 한다. 셀 갱신기
   `/usr/local/lib/rosy-cell/cell_a_autoupdate.py`(저장소 밖 호스트 파일)는 셀이 돌리지 않는
   account·monitoring·postgres·world까지 로컬에 있어야 한다고 검사했다.
2. 갱신기는 항상 가장 최신 서명 후보만 봤다. 최신 후보가 바로 앞 후보에서 빌드한 vision을 재사용하면,
   그 앞 후보를 건너뛴 셀은 영영 설치하지 못한다.
3. `deploy/site/verify_candidate.py`의 로드 이미지 검사도 모든 서비스를 요구했다.

조치: (1)(2) 셀 갱신기를 호스트에서 고침(재사용 검사는 셀 서비스만, 재사용 이미지가 다 있는
가장 최신 후보를 고름; 백업 `*.bak-20261126-*`). (3) PR #987: `--services`가 로드 이미지 검사만
좁히고 서명·아카이브 해시·SBOM·매니페스트 검사는 전체 유지. 셀은 99d090 → 8decccf 순서로
2026-11-27 00:06 설치(fleet·vision healthy).

함께 본 것: 셀의 여러 갱신기가 GitHub 익명 API 한도(시간당 60회)를 나눠 써서 `403 rate limit`으로
한 시간씩 멈출 수 있다. 수동 재실행을 반복하면 한도를 더 빨리 쓴다.

재발 방지: 설치 원본을 저장소 `deploy/site/cell_a_autoupdate.py`(유닛 `rosy-cell-autoupdate.service`·`.timer`,
시험 `test/test_site_cell_autoupdate.py`)로 옮겼다. (1)(2) 수정을 시험이 고정한다. API 사용도 줄였다: 릴리스 목록은
ETag 조건부 요청(304는 한도에 안 셈), 커밋 쌍 비교는 캐시, 실패 기록 커밋은 비교 호출 전에 건너뛴다. 셀에 다시
설치할 때는 `deploy/site/README.md`의 "Arm cell updater (cell-a)" 절을 따른다.
