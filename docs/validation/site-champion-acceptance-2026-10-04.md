# 관제 PC 최고 모델 수용과 로봇 연결 조건

2026-10-04, 앞선 실제 학습·관제 intake 기록은
[model-pc-recording-job-and-site-intake](model-pc-recording-job-and-site-intake-2026-10-04.md)를 참조한다.

기존 최고 모델 `lane-seg-20261004-ed0f9e71`과 그 학습 데이터셋을 관제 PC로 전송했다.
archive, 1,894개 파일 hash/크기와 전체 manifest coverage를 확인했다.
학습 데이터셋 content hash도 복사 전후 버전과 일치한다.

기존 handover로 READY를 만든 뒤 관제 PC에서 원본 19영상 재생과 고정 평가 126프레임을
다시 실행했다. 학습/평가 분리, 기존 최고 모델 이력, 동일 수치 게이트를 유지했다.
intake exit 0/pass, mIoU 0.518525이며 store accepted로 이동했다.
최종 accepted manifest와 모델 파일 hash, READY와 passing intake report를 재확인했다.
앞선 새 후보는 rejected에 보존되어, 이 PC에서 수용과 거절 두 경로를 실제 확인했다.

이 모델은 기존 자동 라벨 기반 차선·벽 후보다. 횡단보도·정지선 정답 부족과
회전교차로 판단 미검증은 해결되지 않았다. accepted는 intake eligibility이며
운영 주행 수용이나 사람 검수 정답 승인이 아니다. 로봇 delivery는 호출하지 않았다.

두 대상 로봇은 운영자 PC의 SSH와 관제 PC의 TCP 검사에서 응답하지 않았다.
관제 mDNS/등록 정보에서 다른 새 주소가 확인되지 않았다. 현재 HOLD와 shadow
포인터는 읽지 못했으므로 과거 상태를 현재 확인 사실로 보고하지 않는다.

관제 Fleet DB는 실제 서비스 계정 UID로 read-only 조회했다. 등록된 두 로봇의
enrollment state는 active지만 CORE event audit은 비어 있다. Fleet dispatch는
2026-10-04 재시작 이후 PROCESS_RESTARTED/disabled다. 등록·인증·dispatch·로봇
연결을 변경하지 않았다. 기존 정적 항목까지 console에는 3 entries가 보고되지만
이것이 3대의 실제 연결 증거는 아니다.

증거: X:/DevTemp/rosy-learning-audit-20261004/site-champion-evidence.
상시 watcher 관리자 설치, 전용 site key/host key/설정, 실제 로봇 통신,
shadow/rollback, owner 실행·Fleet 결과와 DEVICE/FIELD 수용은 남아 있다.
