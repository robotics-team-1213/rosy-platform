# S1 Drive holder 승격 검증 기록

2026-10-13 · branch `refactor/drive-holder-s1` · D-743

## 소스

middleware/control/drive의 217개 추적 파일을 middleware/drive로 승격했다. 외곽 control 안내는 Drive 안내에 통합했다. 기능 알고리즘과 CORE 최종 writer는 변경하지 않았다. source 매핑, sdist, Docker, 서명 배포 입력, 현재 manifest와 시험 소비자를 함께 수정했다. d427_target은 보존했다. 역사 ADR·로그·검증 기록의 옛 경로는 유지했다.

## 증거와 완료 구분

X: 세션 `2026-10-13--170627--drive-holder-s1--9b6514`의 evidence/source-manifest.json에 이전/이후 경로·SHA-256·bytes를 고정했고 reference-edits.json에 참조 수정 목록을 기록했다. 이동 바이트 검증, 독립 리뷰, 원격 시험 결과와 landing은 같은 세션의 evidence/logs에 기록한다. 이 문서의 소스 기록은 아직 시험·main 착지의 증거가 아니며 최종 결과는 Git과 세션 readback으로 확인한다.

기존 responsibility_layout과 drive_behavior_install은 source archive 단독 재빌드·checkout 밖 설치와 단일 module identity를 검증한다. signed model review 및 image closure는 배포 입력 포함과 기존 거절 경계를 검증한다. 실제 Docker/ARM64 이미지 빌드, ROS Jazzy runtime, 장치·현장 수용, push/CI는 이번 범위에서 확인하지 않았다.

## 되돌림

한 단계의 역방향 새 커밋으로 holder, 안내, mapping, Docker·서명 배포 소비자를 같이 복원한다. 기존 이미지와 장치 runtime에는 이번 변경을 적용하지 않는다. S2~S10은 실행 전이다.
