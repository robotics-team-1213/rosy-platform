# rasptank_metal logs

## 2026-10-25 · uncommitted · 무구동 소스 프로파일 준비

- 변경: `rasptank_metal` 설정 패키지, 빈 CORE 모델 층, 0 속도 한계와 물리 기능 비광고, 하네스 소유권을 준비했다. 실제 I/O와 배포 preset은 추가하지 않았다.
- 증거: 테스트 정의 커밋과 원격 실행 요청은 있으나 승인 호스트 자원 문제로 결과 미확인이다. 설정·패키지 정적 점검과 실제 원격 pytest 결과를 구분한다.
- gate 변화: 모든 게이트 HOLD. source-only 후보를 제품·이미지·실물 지원으로 승격하지 않는다.
- 교훈: 미해결 — 제품 모델 결속과 하드웨어 수용은 후속 작업이다.

## 2026-10-25 · uncommitted · 신규 패키지 구조 계약 정렬

- 변경: 계약 시험을 패키지 안으로 옮기고 source contract용 test 의존성과 경로를 선언했다. 정확한 devices family/role 경로와 모듈 기록 링크를 등록했다.
- 증거: 독립 diff 검토에서 기존 package role·패키지별 시험·AGENTS 기록 링크 계약의 누락을 정적으로 확인했다. 원격 실행 결과는 아직 없다.
- gate 변화: 없음. 구조 점검 보완이며 모든 게이트 HOLD 유지.

## 2026-10-25 · eb616252ea · 원격 source 계약 실행

- 변경: 설정/기능 광고는 그대로 유지한다. source selection·load_config·TaskKind 거절과 신규 기종 설정 결속을 승인 시험 호스트에서 실행했다.
- 증거: `p1-green` 관련36, `restructure-green` 결합213에서 패키지 시험 통과, NEW0. 결과는 작업 공간 `rasptank-platform` 검증 기록에 보관한다. 실제 native ament 설치·기체 부팅은 수행하지 않았다.
- gate 변화: SOURCE/LOCAL에 원격 근거 추가. ROS-SIM/ARTIFACT/DEVICE/FIELD는 HOLD 유지.

## 2026-10-25 · 4fdf8c9fee · 잘못 포장된 기종 파일 거절

- 변경: release-owned `deployment-binding.yaml`을 추가해 installed package 안의 모델 ID와 정적 설정 digest를 결속했다. capability 광고·속도·장치 I/O는 바꾸지 않았다.
- 증거: complete Pinky copy·capability-only copy·binding version/model/shape/digest·누락 반례 RED 후 관련153 PASS/NEW0. SOURCE/LOCAL만 갱신하며 실제 native 설치·기체 수용과 구분한다.
- gate 변화: SOURCE/LOCAL 검증 근거 갱신. ROS-SIM/ARTIFACT/DEVICE/FIELD는 HOLD 유지.
