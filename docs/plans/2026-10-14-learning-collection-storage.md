# 학습 수집·영상·저장·재학습 개선 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**상태:** 사용자 요청으로 후속 개선 범위 채택. 아래 단계는 구현 예정이며 외부 업로드·유료 자원 생성·원본 삭제·운영 활성화를 뜻하지 않는다.
**Goal:** 로봇암·주행·일반 영상·외부 자료를 용량과 출처가 보이는 수집부터 검수·고정 학습 자료·추론 피드백까지 연결한다.
**Architecture:** D-755의 공통 의미 계약과 profile, 기존 curation/training/registry 책임을 유지한다. 원본과 파생 자료를 분리하고, 수집·전송·검수·학습 적격성은 각각 판정한다. HF 조직 저장소는 협업 자산을 소유하고 개인 연결은 인증과 작업 이력을 담당한다.
**Tech Stack:** 기존 Python/SQLite/정적 웹, MP4·MCAP·Parquet·JSON manifest, 고정 LeRobot 0.4.4 adapter, 기존 HF import와 registry Hub 전송 도구.

## 현재 기준과 변경 경계

- D-755: 사용자·프로젝트 권한, 고정 revision HF 가져오기, actionless media 계약이 구현되어 있다. 실제 OAuth 등록·운영 전환과 대량 자료 수용은 별도다.
- `learning/curation/perception/learning_imports.py`: 파일당 2GiB, 작업당 8GiB, 최대 256개. 이 제한을 없애는 것만으로 대용량 지원이라고 하지 않는다.
- `learning/curation/perception/media_pipeline.py`: scan → video → verify → reclaim → receipt가 존재한다. 이 도구는 harvest·label·train을 대신하지 않는다.
- `learning/curation/omx/lerobot_export.py`, `native_review.py`: 기존 변환·검토를 재사용한다. D-756의 native 정규화 관절과 SIM rad 데이터는 자동 합치지 않는다.
- `learning/registry/policy/hub_sync.py`: dataset/model 업로드와 고정 commit readback을 재사용한다. 전송 구현을 curation에 복제하지 않는다.
- D-756의 실제 장치·계정·독립 평가 입력 부족은 그대로 유지한다. 현존 합성 시험을 실제 학습 품질로 바꾸어 보고하지 않는다.

## 제품에서 보일 흐름

수집 → 원본 등록 → 품질 검사 → AI 초안 → 사람 검수 → 고정 dataset → 학습·독립 평가 → 승인 모델 추론 → 실패 사례 재수집.

자료 목록에는 프로젝트, 출처 session, 장치/profile, 원본/파생 관계, 시간 범위, 크기, 저장 위치, 전송 상태, 검수 상태, 용도별 허용/보류 이유를 표시한다. 한 개의 완료 표시로 다운로드 성공·검수 승인·학습 적격성을 합치지 않는다.

| 자료 | 필수 수집 근거 | 허용 용도 판단 |
|---|---|---|
| 암 시연 | 카메라별 시각, 관절 이름·순서·단위, state/action, gripper, 보정, 과제·결과 | 행동 동기화·단위·검토를 통과한 episode만 행동 학습 |
| 주행 | 영상, scan/odom, 지도·보정 revision, 요청·실행 제어, 개입·실패 사건 | 인식 자료와 행동 정책 자료의 요건을 구분 |
| 일반 영상·사진 | 출처·이용 조건, 촬영 시각의 확인 여부, 영상 품질, 장면/구간 라벨 | 인식·영상 이해; action이 없으면 모방 학습 보류 |
| 외부 자료 | provider·repo·고정 revision·파일 해시, 계정과 팀 이용 근거 | 접근 가능과 학습·공유 허용을 별도로 검사 |
| 추론 피드백 | 원본 구간, 모델·전처리 revision, 출력, 사람 수정·실패 근거 | 초안으로 재수집; 모델 출력을 정답으로 자동 승인하지 않음 |

## 저장 배치와 보존 원칙

| 위치 | 책임 |
|---|---|
| 현장 수집 버퍼 | 녹화 중 파일, 전송 대기 원본; 완료 세션만 전송 후보 |
| 조직 원본 저장소와 별도 백업 | 승인된 보존 기간의 원본·센서·교시 정보 |
| 모델 PC 캐시 | 현재 검수·학습에 필요한 자료; 작업이 참조하는 자료는 퇴거 금지 |
| HF Bucket 또는 기존 객체 저장소 | 필요한 중간 파일·체크포인트; 변경 가능한 저장소로 취급 |
| HF Dataset/Model 저장소 | 검수된 dataset와 평가된 모델의 고정 버전 |
| Spaces | 우선 기존 공식 viewer의 private 접근·revision 검증; 자료 탐색·시연 |

- 최초 구현은 현황 조회와 전송 계획만 제공한다. 자동 삭제, 원본의 일괄 이전, 저장소 공개 전환을 포함하지 않는다.
- 원본 해시와 복구 가능한 사본을 확인하기 전에는 원본을 삭제 후보로 만들지 않는다. MP4 검증은 scan/state/action의 보존 증거가 아니다. 기존 영상 전용 reclaim 조건을 다른 profile에 일반화하지 않는다.
- 법적·계약상 보존/삭제 요구, 사람이 고정한 자료, 평가 자료, 실행 중 작업 참조를 보존 판정에 반영한다. 향후 삭제 기능은 목록·이유·복구 근거를 검토한 명시 실행으로 분리한다.
- HF Bucket은 Git revision이 없는 변경 가능한 저장소다. 경로만으로 재현성을 주장하지 않고 내용 해시를 확인한다. 확정 학습 입력은 불변 manifest와 versioned repo에 고정한다.
- 개인 다중 계정의 용량을 자동 합산하거나 계정을 바꿔 제한을 우회하지 않는다. 조직별 소유권·quota·권한을 분리한다.

## 단계 1 — 수집·용량 현황과 전송 전 점검 (첫 구현)

**경로:** 기존 `learning/curation/perception/catalog.py`, `learning_workspace.py`, `media_pipeline.py`; 새 `learning/curation/perception/storage_inventory.py`; 화면 `review_app_web/learning.html`, `learning.js`; 새 `test/learning/perception/test_storage_inventory.py`와 기존 `test_learning_workspace.py`.

1. 중복 원본/파생본, 불완전 녹화, 권한 없는 root, 읽기 오류, 디스크 잔여량 부족 fixture를 만든다. symlink를 따라 허용 root 밖을 읽지 않는 실패 시험을 추가한다.
2. 등록된 프로젝트 root만 읽어 논리 자료량·물리 사용량·전송 대기량·측정 시각을 계산한다. 임의 서버 경로를 받는 웹 입력을 다시 열지 않는다.
3. 최근 일별 측정값으로 하루 증가량과 예상 잔여 일수를 표시한다. 자료가 없거나 quota를 확인할 수 없으면 0이나 무제한 대신 미확인으로 표시한다.
4. 전송 전 원격 quota, 로컬 staging/다운로드/변환 임시 공간, 안전 여유분을 따로 계산한다. provider quota API는 공식 지원을 확인한 경우에만 사용하고 수동 설정 값은 출처·유효 시각을 표시한다.
5. 기존 UI 공용 컴포넌트와 명령 검색을 재사용하고 로딩·빈 상태·오류·재시도·열람 권한·모바일을 시험한다. 필요한 새 HTTP 계약은 구현 전에 API reference에 명시한다.

**완료 기준:** 작은 실제 시험 폴더의 파일 합계와 UI/보고서가 일치한다. 읽기 전후 원본 해시가 같고 프로젝트 간 자료명·용량이 노출되지 않는다. 계산 실패가 정상/0으로 보이지 않는다.

## 단계 2 — 대용량 가져오기와 복구

**경로:** `learning/curation/perception/learning_imports.py`, `learning_collaboration.py`, `review_app_web/accounts.js`; 기존 `test_learning_imports.py`, `test_learning_collaboration.py`, `test_learning_accounts_browser.py`.

1. 전송 중단, 서버 재시작, 공간 부족, 계정 철회, 서로 다른 worker의 동일 요청 시험을 먼저 추가한다.
2. 작업 시작 때 고정 revision·파일 목록·크기·해시와 공간 예약을 확정한다. 재시도는 같은 revision·연결 세대를 유지한다. 제한은 자원 계획을 검증한 명시 설정으로만 확장한다.
3. provider가 지원하는 파일별 부분 재개를 사용한다. Range 응답의 상태·offset·전체 크기·identity를 검사하고 200 전체 응답을 부분 파일 뒤에 붙이지 않는다. identity 변경 시 재사용을 거부한다.
4. 최종 전체 해시 검증 뒤 원자적으로 완료 등록한다. 불완전 파일을 viewer/학습에 제공하지 않는다. 작업·파일별 진행률과 실패 이유, 취소·재시도를 기존 화면에 표시한다.
5. 작은 결정적 fixture로 경계 시험을 하고, 별도 opt-in 원격 대량 시험에서 기존 8GiB를 넘는 전송의 최대 메모리·디스크 최고점·재개량·해시를 측정한다. 노트북에서 대량 파일을 만들지 않는다.

**완료 기준:** 중단 후 재개가 다른 revision 또는 계정으로 바뀌지 않는다. 손상/공간 부족/철회는 보류되고, 검증된 파일만 등록된다. 제한 상향만으로 완료 처리하지 않는다.

## 단계 3 — 품질·계보와 고정 학습 자료

**경로:** `contracts/learning/src/rosy/contracts/learning/media.py`, 기존 artifact 계약; `learning/curation/perception/media_pipeline.py`, `review_evidence.py`; `learning/curation/omx/native_review.py`, `lerobot_export.py`; `learning/training/perception/recording_job.py`; 기존 media/episode/OMX 통합 시험.

1. 영상 디코딩 실패·누락 frame·clock 불일치·단위 혼합·보정 미확인·행동 없는 영상 fixture를 추가한다.
2. 기존 schema를 임의 확장하지 않는다. 누락 의미는 버전 있는 sidecar/profile 또는 명시 migration으로 정의하고 영향 reader를 열거한다.
3. 원본 session → 파생 영상/라벨 revision → dataset → 모델 → 추론 결과를 연결한다. 재인코딩·재라벨된 동일 session은 같은 split 그룹을 유지한다.
4. ontology revision과 학습 클래스 매핑, 학습/추론 전처리를 고정한다. AI 초안과 사람 승인을 구분하고 모델별 실패 사례를 다음 검수 후보로 묶는다.
5. 기존 LeRobot 0.4.4 reader로 다시 열어 frame/episode 수, 다중 카메라 시간, 관절 순서·단위와 변환 손실을 확인한다. 최신 문서의 기능을 현재 고정 버전 지원으로 간주하지 않는다.

**완료 기준:** 자료 화면에서 보류 이유와 부모 원본을 추적할 수 있다. 행동 없는 영상은 모방 학습에 들어가지 않는다. 같은 원본의 train/eval 누출과 승인 후 덮어쓰기를 거부한다.

## 단계 4 — 조직 Hub 전송과 저장소 운영

**경로:** `learning/registry/policy/hub_sync.py`, `learning/registry/policy/test/test_hub_sync.py`; 기존 계정 연결 서비스와 학습 화면. Bucket adapter는 계약 검토 후 같은 registry 소유 영역에 최소 구현한다.

1. 기존 prepare/upload/readback을 재사용하여 UI의 프로젝트·사용 계정·대상 org/repo·파일·크기·공개 범위·고정 revision을 연결한다. 외부 게시 권한은 기존 import/manage로 자동 대체하지 않고 D-755에 따라 별도 계약을 확정한다.
2. 게시 전 검토 결과와 실제 전송 결과를 구분한다. 전송은 명시적으로 승인된 고정 목록에만 수행하고 완료 commit의 다운로드 해시와 reader 재개방 결과를 저장한다.
3. Bucket은 실제 필요가 확인되면 추가한다. overwritten object·삭제·권한 취소·quota 실패를 시험하며 Dataset import와 같은 immutable revision이 있다고 가정하지 않는다.
4. 저장 한도·청구 예상은 측정 시각과 가격 기준을 표시한다. 자동 유료 증설·구독·다른 계정 fallback은 제공하지 않는다.

**완료 기준:** 실제 org/private repo와 계정이 제공되면 승인한 자료의 private 왕복·고정 SHA·해시·reader를 확인한다. 그 전에는 대역 시험 완료로만 기록한다.

## 단계 5 — Spaces 탐색과 추론 피드백

**경로:** D-756의 공식 viewer 검토 경로, 기존 `learning/registry/policy/hub_sync.py` receipt, `learning/curation/perception`의 기존 검수 intake와 학습 화면.

1. 공식 viewer로 가능한지 먼저 확인하고 자체 Space는 필요한 차이가 있을 때만 만든다.
2. 선택 dataset SHA·episode·영상 구간을 보여준다. 비인가 사용자의 private 자료 접근과 secret 노출을 차단하고 재시작 후 같은 SHA가 열리는지 확인한다.
3. 추론 실패/불확실성/사람 수정 사례를 원본·모델·전처리 버전에 묶어 재수집한다. 중복·흐림 탐지와 장면 분할은 검수 우선순위를 돕고 자동 정답 승인은 하지 않는다.
4. Spaces 임시 디스크를 원본 저장소로 사용하지 않는다. GPU 실행·외부 영상 전송·유료 자원은 별도 명시 운영 설정과 수용이 있어야 한다. 장치 제어를 Space에 넣지 않는다.

**완료 기준:** 읽기 전용 탐색 → 사례 선택 → ROSY 검수 후보 등록 → 계보 readback이 연결된다. 실제 학습/실물 성공률은 별도 평가로 남는다.

## 실행·검증 순서

각 단계는 실패 시험 작성 → 해당 파일만 커밋 → canonical 원격 RED 확인 → 최소 구현 → 커밋 → 같은 원격 시험 GREEN → known_failures 비교 → 실제 HTTP/UI·영속 readback → 문서 갱신 순서로 수행한다. pytest는 노트북에서 실행하지 않는다.

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<managed-session>/logs/<stage> -- <affected-test-paths> -q
python test/known_failures.py X:/DevTemp/<managed-session>/logs/<stage>/run-1.txt
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

브라우저 시험은 원격 runner의 Chromium opt-in으로 수행한다. 문서만 바뀌면 `test/test_harness_contracts.py`, `test/test_network_topology_contracts.py`와 문서 배치 검사를 수행한다. 명시된 커밋·머지 요청 범위에서만 `tools/land.py`로 착지하고 push·배포·외부 서비스 수용은 별도 기록한다.

이번 계획의 첫 실행 묶음은 단계 1이다. 다음 단계가 편리하다는 이유로 계정·원본·유료 저장소 준비를 가정하지 않는다. 실제 독립 검수·평가 자료가 쌓이기 전에는 합성 시험을 학습 품질로 보고하지 않는다.

## 용량 산정과 확인할 입력

카메라별 실제 파일 bytes/시간, 카메라 수, 하루 녹화 시간, 센서 bytes, 파생 자료 비율, 보존 기간, 백업 사본, 네트워크 실효 전송률을 측정한다. 가정상 카메라당 8Mbps면 3.6GB/시간이고 3대 × 8시간 × 30일은 영상만 2.592TB다. 이 예시를 현장 측정값으로 표시하지 않는다.

운영 전 필요한 입력은 프로젝트/저장소 관리자, 원본 root·백업 위치, 수집 rig, 실제 자료 이용 조건, 조직 소유 HF 대상, 보존 기간과 예산이다. 입력이 없어도 단계 1의 격리 fixture와 read-only 보고서 구현은 진행할 수 있다.

## 공식 자료와 가격 취급

2026-10-14 검토 자료. 가격·quota는 구매/배포 시 다시 확인하고 제품 상수로 고정하지 않는다.

- [Hub storage limits](https://huggingface.co/docs/hub/storage-limits): 무료 private 100GB, PRO 1TB, Team/Enterprise 좌석당 private 1TB, 유료 초과 기본 $18/TB/월. 구독·실행 비용은 별도.
- [Spaces overview](https://huggingface.co/docs/hub/spaces-overview), [Spaces storage](https://huggingface.co/docs/hub/spaces-storage): 기본 50GB 임시 디스크와 attached volumes. 영구 원본 저장의 대체물이 아님.
- [Storage Buckets](https://huggingface.co/docs/hub/storage-buckets): 변경 가능·비버전 저장소. 별도 불변 참조와 복구 전략 필요.
- [LeRobotDataset v3](https://huggingface.co/docs/lerobot/en/lerobot-dataset-v3): MP4/Parquet/metadata 구성; 우리 고정 버전의 실제 reader 수용은 별도.
- 저장소 계약: [D-755](../adr/D-755-learning-data-and-collaborative-provider-accounts.md), [D-756](../adr/D-756-omx-imitation-preparation-and-resumption-gates.md).
