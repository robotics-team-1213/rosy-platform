# S1 Drive holder 승격 검증 기록

2026-10-13 · branch `refactor/drive-holder-s1` · [D-743](../../adr/D-743-drive-holder-promotion.md)

## 소스와 설치

middleware/control/drive의 217개 추적 파일을 middleware/drive로 승격했다. 외곽 control 안내는 Drive 안내에 통합했다. source mapping, sdist, Docker context/COPY와 내부 fallback, 서명 배포 prefix/필수 파일, 현재 manifest·harness와 시험 소비자를 함께 수정했다. 설치 control.*, core_features.*, navigation과 CORE 최종 writer는 유지했다. immutable d427_target과 역사 ADR·로그·검증 기록의 옛 경로는 보존했다.

초기 이동은 215파일 byte-identical, Drive 안내와 생성 nav2 index 2파일 변경이다. 이후 main의 동료 수정도 옮긴 경로에 통합했으며 최신 main 입력 217파일과 비교해 알고리즘 드리프트 0을 확인했다. 독립 Safety source 리뷰는 Codex /root/delivery_review PASS, Safety-Review trailer와 range 검사 PASS다.

## 원격 검사

원격 source candidate commit `b3687f8dec`에서 3묶음 **17,827 passed / 929 skipped / NEW 0**이다. CORE·구조 8,027/567, perception·배포 4,760/116, Fleet 5,040/246이다. 929 skipped를 통과로 집계하지 않는다. responsibility_layout과 drive_behavior_install은 sdist 단독 재빌드·checkout 밖 설치·기존 module identity를 검증했다. model review와 image closure는 서명 배포 입력과 기존 거절 경계를 검증했다.

초기 실행의 split Path 참조 누락으로 navigation collection 오류 3건, 다음 실행의 허용 폴더 목록 누락으로 구조 검사 실패 2건이 있었다. 해당 테스트 참조·목록을 고치고 옛 경로 거절 사례를 추가했으며 위 최종 source 실행에서 모두 통과했다. 현장 시험 PC의 SSH 연결이 55%에서 끊긴 별도 실행은 실패로 보존하고 통과로 집계하지 않았다. 중단한 시험 경로에 남은 프로세스가 없음을 readback했으며 모델 PC로 재실행했다. known_failures 목록에 신규 실패를 추가하지 않았다.

## 최신 main과 착지

source 검사 이후 main delta는 UI 평가/SSH 안내·도구·시험이다. Drive·Fleet와 설치 source mapping 변경이 없음을 git diff로 확인했다. 이 차이와 현재 구조·sdist/서명/image closure를 원격 집중 재검사하고 known_failures·lint 이후 tools/land.py의 ff-only 착지로 닫는다. 범위는 SSH enroll/share, harness/document placement, module/platform/Safety 구조, Drive 설치, perception responsibility layout, model review, image closure다. 완료 결과와 최종 착지 commit은 아래 evidence의 final readback이 정본이며 이전 source 검사 SHA를 최신 metadata 검사 SHA로 바꿔 집계하지 않는다.

X: 세션 `2026-10-13--170627--drive-holder-s1--9b6514`의 evidence/source-manifest.json, merged-source-readback.json, independent-review.json, source-test-gate.json, landing-readback.json과 logs에 원본/새 경로·hash·크기·후속 delta·시험 exit·main readback을 보존한다. [실행 계획](../../plans/2026-10-13-drive-holder-s1.md)을 따른다.

## 증거 제한과 되돌림

FULL CI는 아직 남아 있으며 push, 실제 Docker/ARM64 이미지 빌드, ROS Jazzy runtime, 장치·현장 수용은 확인하지 않았다. S2~S10과 P2/P3은 후속이다. source relocation은 명령 권한 개선이나 실제 배포 증거가 아니다.

역방향 새 커밋으로 holder·안내·mapping·Docker·서명 배포 소비자를 같이 복원한다. 기존 이미지·장치 runtime과 공유 main의 동료 WIP는 이번에 변경하지 않았다.
