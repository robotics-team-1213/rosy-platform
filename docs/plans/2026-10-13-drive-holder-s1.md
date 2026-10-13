# S1 Drive holder 승격 실행 계획

**날짜:** 2026-10-13 · **브랜치:** `refactor/drive-holder-s1`
**계약:** [D-743](../adr/D-743-drive-holder-promotion.md), [전체 계획](2026-10-13-folder-responsibility-cleanup.md)

## 범위와 순서

1. D-738 S1의 최종 트리를 middleware/drive로 명시한다. 안쪽 Drive holder 217개 추적 파일을 한 층 올리고 바깥 안내를 통합한다. 기존 소유권 ID와 설치 import·entrypoint는 유지한다.
2. perception/core_features source fallback, sdist manifest, harness 현재 root, safety anchors, Docker context/COPY, signed source allowlist, review installer, 개발 sync·학습 안내·시험의 source 경로를 같이 갱신한다. 역사 ADR·로그·검증 자료는 바꾸지 않는다.
3. 이동 파일 SHA-256과 크기 및 mapping 경로를 확인한다. 기존 sdist-alone→wheel→checkout 밖 설치, Drive feature identity, signed review, image closure 시험을 원격 PC에서 실행한다. 독립 Safety 리뷰와 NEW 0을 확인한다.
4. 정확한 파일 목록만 커밋하고 tools/land.py --tests auto로 최신 main을 통합·재검사·ff 착지한다. push/배포는 이번 범위가 아니다.
5. S1 착지 후 S2 입출력 inventory→S2/S3 판단/ROS 조립 분리→S4/S5 이름 구분→S6 관측 holder 범위 확정→S7/S8 경계 분리→S9/S10 소비자 이전 순서를 유지한다. 각 단계는 별도 커밋·검증·착지다.

## 완료와 되돌림

[source와 검사 기록](../validation/drive-holder-s1-2026-10-13/result.md)에 소스/검사/local main/배포/장치 gate를 구별한다. 계약 보완과 소스 변경만으로 배포 수용을 주장하지 않는다. 실패는 branch에서 고치고 같은 gate를 재검사한다. 역방향 새 커밋으로 holder·mapping·배포 경로를 함께 복원하며 동료 WIP를 치우지 않는다.
