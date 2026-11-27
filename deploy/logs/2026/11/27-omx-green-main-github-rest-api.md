## 2026-11-27 · uncommitted · OMX 자동 갱신의 신뢰 출처를 서명된 green-main 포인터로(GitHub REST API 대신)

- 변경: omx_autoupdate.py에 trust_source(platform|github)를 더했다. platform이면 omx_autoupdate_platform.PlatformHost가 서명 PC의 green-main 포인터(ed25519, candidate_signing 봉투)에서 머리 커밋, ci-result, 커밋 서명 여부를 읽는다. 조상 확인은 커밋만 받은 로컬 git 미러로 한다. 포인터가 1시간보다 오래되면 거절한다. 포인터나 미러를 못 읽으면 transient로 끝나고 아무것도 바꾸지 않는다. 생산자는 deploy/site/green_main_pointer.py다. 검증기가 없는 옛 릴리스에서는 그 회차만 github로 받는다. platform_url이 없는 설정은 그대로 github다.
- 증거: 원격 pytest test_omx_autoupdate*.py, test_site_green_main_pointer.py, test_model_pc_autoupdate.py, test_update_gate.py 325 passed(e5574a6df9). 서명 검증을 지운 변이에서 새 시험 2개 빨간불. 실제 저장소에 대한 생산자 --dry-run
- gate 변화: 없음(ci-result 통과, 후손, hotfix floor, smoke, 셀 유휴 관문 그대로, 확인 주체만 서명 PC로 옮김)
- 결정: D-805 7 '서명 키가 준비되면 같은 서명으로 맞춘다'의 실행. 셀 설정과 서명 PC 타이머는 병합 뒤 적용
- 교훈: 없음(셀 수용 전)
