# ROSY 파이프라인 완성도 평가와 완료 작업 보고서

평가일: 2026-10-19 KST. 목적: 주요 파이프라인의 현재 도달점과 완료를 막는 조건을 구분하고, 다음 작업 순서를 정한다.

후속 실행: [성공 주행 구현의 보존·통합·검증](../validation/pinky-success-integration-2026-10-19/result.md).
원본 성공 소스의 새 재실행은 PASS했다. main 기반 통합 후보는 1회 성공 후 정체로 실패했고,
전방 정지 우선순위를 수정한 후보도 다른 코너에서 실패해 반복 주행 수용은 HOLD다.
추가 [코너 수정 검증](../validation/pinky-corner-completion-2026-10-19/result.md)에서 정렬 상태 수명과 곡선 거리 판정을 수정하고 원격 영향 회귀 6,832건을 통과했다. 최종 소스 SIM은 1 PASS/1 FAIL이며 관측·경로 안내 불일치 후 realign HOLD가 남아 주행 파이프라인 완료로 판정하지 않았다. 기존 trip의 자동 REALIGN은 별도 미수용 계약이다.
아래 평가는 최초 조사 시점의 근거와 한계를 보존한다.

## 1. 현재 판단

**주요 파이프라인은 완성 계획을 세우는 관점에서 6개 축으로 묶을 수 있다. 코드 연결과 부분 통합 실행은 상당 부분 확보했지만, 아래 조사 범위에서 실물 과제·운영 수용·실패 환류까지 모두 완료했다고 판정할 축은 없다.** 이 6개는 기존 모듈의 공식 재분류가 아니라 이번 보고서의 작업 분류다.

지금 필요한 일은 모든 연결 코드를 새로 만드는 것이 아니다. 이미 연결된 경로에 대해 버전과 성공 기준을 고정하고, 반복 실행·독립 평가·설치 확인·실제 과제 결과를 결속하는 것이 우선이다. 학습 정답 부족, 재현되는 주행 실패, 실물 검증 공백은 서로 다른 작업으로 관리해야 한다.

특히 다음 두 사실을 함께 반영해야 한다.

- **주행:** learned drivable 기반 Gazebo 완주·정지 성공 기록이 있다. 그러나 다른 실행은 도착 오차로 실패했고, 최신 재점검도 정체로 실패했다. 연결 성공은 확보했으나 반복 수용은 미완료다. [E2]
- **암:** 10/19 Fleet 인증·승인 lease → CORE HTTP → 별도 LeRobot 프로세스 → OMX owner → Gazebo 이동·취소를 같은 실행에서 확인했다. 이 시험은 고정 SIM 목표이며 학습된 모델·실물 파지 성공을 검증하지 않았다. [E3]

전체 완료율을 백분율로 제시하지 않는다. 독립 평가를 통과하지 못한 모델을 배포 도구의 완성도로 상쇄할 수 없고, 코드 시험 수를 실물 성공률로 환산할 수도 없기 때문이다.

## 2. 평가 범위와 기준

### 조사 기준

- 플랫폼 소스 조사 기준 HEAD: commit `bd3c9fe3e4ca91ba4cca4f12dd8d92ef9c1fec8c`.
- `rosy-vault` 조사 기준 HEAD: commit `c5da5c36f0046eb7b0bccdf1b5367b98e4720cad`.
- 현재 소스의 주요 진입점, 관련 시험 파일 위치, 모듈 상태표, 계획·검증 문서, OMX SIM JSON receipt, 기존 학습·주행 점검 보고서를 확인했다.
- 활성 워크트리 목록도 확인했다. 모든 워크트리의 변경과 외부 원시 로그를 전수 감사한 것은 아니다. 주행 워크트리의 실행 결과는 해당 실행 SHA의 증거로만 사용했다.
- `62971299f…`의 OMX SIM 성공 revision과 `4ee3f3aaa…` candidate가 조사 HEAD의 조상임을 git으로 확인했다. 이는 현재 main 이력에 포함됐다는 뜻이며 최신 HEAD를 다시 실행했다는 뜻은 아니다.
- 주행 재점검 revision `ff8eca4d…`는 조사 HEAD의 조상이 아니었다. 해당 실패를 현재 main의 재시험 결과로 표기하지 않는다.
- pytest·Gazebo·GPU 학습·브라우저·실물 시험을 이번 보고서 작성 중 새로 실행하지 않았다. 원격 호스트나 로봇에도 접속하지 않았다. 아래 수치는 보존 기록이다.
- 제품 코드·설정·git 상태를 바꾸지 않고 이 보고서만 작성했다. 기존 `aff1.log` 등 다른 작업 파일은 건드리지 않았다.

### 완료를 판정하는 단계

| 단계 | 필요한 증거 | 이 단계만으로 알 수 없는 것 |
|---|---|---|
| 구현 | 입력과 출력, 소비자, 오류 처리, 실행 owner가 실제 소스로 연결됨 | 배포된 환경에서 작동하는지 |
| 코드 검증 | 실행 SHA·시험 선택·결과·skip·실패 분류가 연결됨 | 모델 품질과 물리 과제 성공 |
| 통합 실행 | 같은 실행에서 입력부터 실제 owner 결과까지 추적 가능 | 다른 조건에서의 반복 성공 |
| 장치 수용 | 설치 revision·보정·실제 사용·정지·과제 결과 확인 | 현장 대표 조건의 운영 품질 |
| 운영 완성 | 사전 정한 대표 조건의 반복 수용, 장애 처리·복구·rollback·환류 확인 | 검증 범위 밖의 모든 상황 |

`STATUS.md`의 SOURCE/LOCAL/ROS-SIM/ARTIFACT/DEVICE/FIELD는 기존 공식 gate다. 위 표는 보고서 해석을 위한 기준이며 공식 gate를 수정하거나 승격하지 않는다. 오래된 HOLD와 최신 부분 성공이 함께 있을 때 둘 다 기술한다. [E1, E11]

## 3. 6개 축의 완성도 요약

| 축 | 실행 흐름 | 확보한 수준 | 가장 가까운 미완료 관문 | 현재 판정 |
|---|---|---|---|---|
| ① 관측·World·주행 | 센서/영상 → 자세·도로 관측 → Drive → CORE → 도착·정지 | 소스 연결, ROS/SIM 슬라이스, learned drivable 완주 사례 | 정체·도착 오차를 해결하고 고정 조건 반복 수용 | 부분 통합 성공, 안정성 미완료 |
| ② 사용자 요청·Fleet 실행 | 인증/Console/채널 → Task/Mission/trip → admission → owner → readback·원장 종결 | 주요 경로·원장·worker 연결, 원격 회귀 기록 | 실제 설치본에서 작업 결과·재시작·자원 해제의 종단 수용 | 소프트웨어 연결 확보, 운영 수용 미완료 |
| ③ 인식 데이터·학습·전달 | 수집 → 사람 검수 → dataset → train/eval → registry → shadow/paint → runtime | 검수·학습·전달 코드, 기존 모델·사람 작업·SIM 사용 증거 | 현재 목적의 승인 정답과 원본 촬영 단위 독립 평가 | 연결 확보, 평가 적격성·승격 미완료 |
| ④ 암 시연·학습·실행 | 보정/시연 → ACT → 재적재·평가 → 정책 → 실행 owner → 물리 목표 | 직접 device-core 경로와 플랫폼 경로, 플랫폼 고정 정책 SIM 종단 성공 | 실제 시연 학습 모델과 과제 성공 판정의 결속 | SIM 실행망 확보, 학습 실물 과제 미완료 |
| ⑤ Decision·사건·환류 | 사건 → 규칙/모델 제안 → admission → 실행·인계 → 검수·다음 후보 | 기존 복구·advisory·평가·export/registry 코드와 회귀 | 실제 제공자/격리 수용, 독립 사람 정답, 현장 그림자 평가 | 기존 경로 부분 구현, 모델 운영·전체 환류 미완료 |
| ⑥ 빌드·릴리스·설치·운영 | source → artifact/서명 → 설치·SD → 부팅/graph → 상태·업데이트·rollback | 배포 도구·서명 검증·SD 안내·호스트 시험 기록 | 적격 최신 이미지와 실제 매체·첫 부팅·업데이트 수용 | 배포 절차 구현, 최신 설치·실기 완료 미입증 |

①·③은 같은 주행 제품의 실행면과 모델 생산면이다. ②는 여러 장치를 조율하고, ⑥은 모든 축을 실제 설치본으로 전달한다. ⑤의 환류는 ③·④에도 걸친다. 이를 각각 별개의 제품으로 만들 필요는 없다.

## 4. 축별 평가와 완료 조건

### ① 관측·World·주행

현재 관측 → Drive → CORE 연결과 World의 현재 자세 projection은 존재한다. World `bridged`는 관측 anchor를 odom으로 이어가는 현재 자세 추정이며 행동 조건부 미래 예측 모델이 아니다. 소스에도 주행 거리·회전·anchor 나이에 따른 DEGRADED 판정이 있다. [E1, E12]

learned drivable의 r51a는 완주 후 목표 거리 0.108m로 PASS였다. r51b는 Fleet가 `arrived`를 기록했지만 정착 거리 0.156m로 당시 허용 0.15m를 넘었고, 기록 끝에 약 0.04m/s로 움직여 FAIL이었다. 두 실행은 차선 복귀 검사를 끈 조건이었다. [E2]

최신 보존 재점검 `ff8eca4d…`는 약 523.5초 뒤 `stall`로 실패했다. 마지막 구간은 위치 추정 LOCALIZED를 유지하며 선속도 0과 좌우 조향·회전을 반복했다. 실제 주행 구간 keep_debug는 learned_drivable 1,465건, fallback 1건이었다. 모델이 연결되지 않은 시험으로 설명할 수 없지만, 이 기록만으로 모델·영역 선택·경로 안내·집행 중 단일 원인을 확정할 수도 없다. [E2]

**완료까지 할 일**

1. 수용할 소스·모델·지도·보정·실행 옵션을 고정한다. 현재 main과 별도 워크트리 결과를 분리한다.
2. 같은 실패 구간에서 프레임·선택 영역·경로 오차·Drive 후보·CORE 최종 명령·odom을 시간으로 결속해 정체 원인을 좁힌다.
3. `arrived` 이벤트와 별개로 최종 거리·속도·정지 유지·경로 준수를 검사한다. 운영에 필요한 검사를 끈 실행은 부분 시험으로 남긴다.
4. 사전 정한 시작 자세·조명·가림·장애물 조건과 반복 횟수로 수용한다. 그다음 실제 장치에서 보정·지연·정지 거리를 확인한다.

완료 산출물: 실패 재현과 수정 근거, 동일 버전 반복 실행표, 실패·중단 포함 분모, 실물 설치·정지·과제 readback. 현재 가장 구체적인 실행 결함 조사 대상이다.

### ② 사용자 요청·Fleet 작업 실행

인증·Console/채널 접수, 대화 후보, navigation Task, Mission/Cell Job, trip·traffic, formation, 사건 복구, background worker의 연결이 기존 전체 흐름 점검에 정리돼 있다. 현재 Fleet `app.py`와 Task 결과 원장에서도 실제 연결과 attempt 결속 코드를 확인했다. [E1, E13]

기존 작업은 결과 조회 지연이 다른 owner의 종결을 막는 문제와 worker 종료·자원 회수 문제를 수정하고 원격 회귀를 남겼다. 그러나 이 시험은 다중 실물 로봇·교통 신호·물체 파지 전체의 수용을 대신하지 않는다. Mission Action 성공과 실제 목표 증거도 분리돼 있다. [E1, E4]

**완료까지 할 일**

1. 첫 운영 범위를 단일 로봇 navigation Task와 trip으로 좁혀, 요청 ID → attempt → 실제 owner → terminal → 자원 해제까지 같은 실행으로 확인한다.
2. 거절·응답 불명·연결 단절·재시작·취소를 실행하고 UNKNOWN 점유와 중복 dispatch 방지를 확인한다.
3. 그 후 Mission/Arm, Cell Job, 다중 로봇/신호, formation을 각각 별도 수용한다. 사용하지 않을 경로는 첫 완료 범위에서 제외했다고 명시한다.

완료 산출물: 설치 revision, 기명 요청·승인, owner receipt, 물리 결과, 원장 종결, lease/claim 정리, 재시작 후 동일 attempt 대조 기록.

### ③ 인식 데이터·학습·평가·전달

데이터나 사람 검수가 전혀 없는 상태는 아니다. 기존 v2 2,769쌍과 사람 수정 기록이 있다. 다만 동일 이미지 hash가 split에 중복되지 않는다는 사실만으로 독립 평가를 보장하지 못했다. 원본 영상 추적에서 2,519장이 upstream에 연결됐고, 연결된 다섯 원본 그룹이 여러 split에 걸쳤으며 250장은 연결되지 않았다. 기존 자료는 개발 기준선으로 보존하고 독립 최종 시험으로 승격하지 않는다는 기록이 있다. [E5]

현재 `ReviewPipeline.prepare()`는 승인 mask 존재를 검사하고 owner·출처 문맥을 사용한다. `deliver.py`에는 shadow와 수동 paint pointer의 구분·rollback 경로가 있다. 도구 연결을 추가하는 것만으로 승인 정답과 독립 평가가 생기지는 않는다. [E14]

**완료까지 할 일**

1. road-surface/차선/경계의 현재 정답 의미와 제외 영역을 고정한다. 기존 사람 작업을 다른 의미의 정답으로 자동 전환하지 않는다.
2. 원본 촬영 세션·capture group 단위로 개발·평가를 분리하고 최종 평가 세션을 학습에서 예약 제외한다.
3. 독립 검수자가 승인한 정답으로 기존 기준선과 후보를 같은 조건에서 평가한다. 클래스별 품질과 위험 오검출·누락을 함께 보고한다.
4. 접수한 모델의 hash를 실제 runtime 관측에 결속하고 learned 사용률·fallback 사유·동시 부하 지연을 측정한다. ①의 주행 수용도 통과해야 운영 채택한다.

완료 산출물: 출처·검수자·정답·split manifest, 기준선 대비 평가, 고정 artifact, 전달 receipt, 실제 소비와 과제 수용 기록. 정답 및 평가 자료의 적격성은 모델 확대보다 앞선 관문이다.

### ④ 암 시연·학습·실행

암에는 두 경로가 있다. 직접 경로는 `rosy-vault`의 보정·녹화 잠금 → 외부 LeRobot 학습 → 모델/processor → 정책 루프 → SafeDriver다. 플랫폼 경로는 시연/export → ACT 학습·재적재·평가 → CORE/Fleet 승인·lease → OMX owner다. 두 경로의 단위·보정·실행 권한을 섞어 완료 판정하면 안 된다. [E6]

**10/19 플랫폼 진전:** 보존된 runner/native receipt에서 고정 SIM 목표 +0.01rad의 관절 변화와 SUCCESS, 승인 철회 후 약 0.295초의 cancel 관측·CANCELED/HOLD, 재접속 거절을 확인했다. 이것은 같은 실행의 통합 증거다. 합성 관리자 승인과 fixture 설치 binding을 사용했고 학습 checkpoint는 없었다. 종료 뒤 Destroyable 경고도 남았다. [E3]

앞선 보고서의 ‘플랫폼 lease 연결이 남음’ 설명은 SIM에 대해서는 최신 상태가 아니다. **현재 남은 핵심은 고정 SIM 정책으로 확보한 실행망에 적격 학습 산출물과 실제 과제 판정을 연결하는 일**이다. 직접 경로의 시간 기반 `SUCCEEDED`도 파지·배치 성공 판정과 구분해야 한다. [E3, E6]

**완료까지 할 일**

1. 첫 실물 과제의 경로를 직접 device-core 또는 플랫폼 중 하나로 명시한다. 선택하지 않은 경로를 삭제할 필요는 없다.
2. 시연 episode·rig·카메라·관절 단위·보정 revision을 고정하고 실제 시연으로 학습한다.
3. 별도 프로세스 재적재와 독립 episode 평가로 기준선·위험 출력·지연을 비교한다. 현재 `native_cycle.py`에 학습/재적재/평가 도구가 있으므로 이를 사용한다. [E15]
4. 실제 학습 checkpoint로 SIM 과제를 수행한다. 고정 목표 probe 결과는 실행망 증거로 별도 유지한다.
5. 선택한 실물 경로의 승인·한계·정지 조건을 충족한 뒤 짧은 과제를 수행하고, 독립 관측으로 파지·운반·배치 결과를 판정한다.

완료 산출물: 실제 시연 출처, checkpoint/processor hash, 독립 평가, 보정 결속, 실행 권한·정지 기록, 물리 과제 성공·실패·중단 결과. 플랫폼 SIM 성공을 실물 활성화 승인으로 사용하지 않는다.

### ⑤ Decision·사건 처리·실패 환류

기존 규칙·lane recovery·advisory 제안·admission·실행/인계와 사건 export/검수/registry 경로가 있다. Decision deliberation의 소스·가짜 제공자 통합 회귀도 기록돼 있다. 과거 설계의 ‘목표 모듈 미구현’을 현재 전체 코드 부재로 읽어서는 안 된다. [E1, E7]

반면 보존된 호스트 admission 기록에는 실제 격리 실행 실패와 설치 수용 공백이 있고, 후속 host runner 기록도 실제 제공자·현장 수용을 HOLD로 유지한다. 이는 해당 기록 시점의 사실이며 이번에 현재 호스트를 재진단한 결과는 아니다. [E7]

**완료까지 할 일**

1. 막힘 정체 사실을 내는 VLM과 Mission/Task 후보를 내는 숙고형 모델의 목적·입출력·평가 세트를 분리한다.
2. 사건 ID에 관측·명령·실행 결과·사람 판정을 묶고 대표 사건의 분모와 누락 범위를 측정한다.
3. 고정 제공자/profile의 실제 격리·버전·비용·timeout·실패 처리를 수용하고 독립 사람 정답으로 평가한다.
4. 현장 그림자에서 기존 규칙과 제안을 비교한 뒤 기존 admission을 통해 제한적으로 수용한다. 모델에는 직접 장치 명령 권한을 주지 않는다.
5. 실패 1건을 검수 → 새 dataset/후보 → 독립 평가 → 승인 → 적용/rollback까지 한 회전 추적한다. 자동화 여부보다 이 회전의 실제 증거가 먼저다.

완료 산출물: 실제 제공자 수용 receipt, 사건·정답 세트, 독립 평가, 그림자 결과, 기존 owner를 통한 실행 결과, 다음 버전 환류 기록. door/arm 범용 자동 개입과 미래 World 예측은 첫 완료 범위와 별도로 계약을 확정할 확장이다.

### ⑥ 빌드·배포·설치·운영

SD 준비 도구는 기존 작성기에 위임하고 등록·삭제 확인·전체 readback을 유지한다. 10/18 기록은 네이티브 self-check 6 PASS와 원격 366 passed/30 skipped를 남겼지만 디스크·작성기는 fixture였다. 실제 카드·첫 부팅·자동 업데이트 수용은 체크리스트에 남아 있다. [E8]

당시 조회에서는 최신 flashable artifact를 확보하지 못했고, 로컬의 서명 검증된 9/22 전체 이미지는 자동 업데이트 도입 이전 revision이었다. 이것은 10/18의 확보 상태이며 지금 원격 저장소에 이미지가 없다고 새로 확인한 주장은 아니다. 현재 적격 이미지를 다시 식별해야 한다. [E8]

**완료까지 할 일**

1. 설치할 source revision과 전체 이미지·payload·서명·SBOM을 식별하고, 기대하는 기능이 그 revision에 포함됐는지 확인한다.
2. 대상 SD에 대한 기존 확인 절차 아래 쓰기·전체 readback을 수행한다.
3. 첫 부팅에서 실제 서비스·ROS graph·장치 ACL·모델 pointer·설정·보정과 최종 command owner를 확인한다.
4. 업데이트 성공, 실패 시 이전 버전 유지/복귀, 서비스 재시작, 장치 상태 readback을 실행한다.

완료 산출물: 서명·hash·source 결속, 매체 readback, boot/service/graph 증거, 실제 모델 사용, 업데이트와 rollback receipt. 배포 도구 시험과 실기 설치를 별도로 완료 표시한다.

## 5. 학습 주행의 보조 경로

인식 모델+기존 Drive와 다음 두 연구 경로를 하나의 완료율로 합치지 않는다.

| 경로 | 확보한 증거 | 첫 운영 파이프라인과의 관계 |
|---|---|---|
| 영상 → 속도 모방학습 | 실제 MCAP 기반 학습·재적재·정책 산출물. 10/04 기록은 expert 의도·선/각속도 기준선 조건으로 등록 거절 | 채택 가능한 정책 수용이 선행. 현재 주행 실행망 완성의 필수 의존성으로 만들지 않음 |
| Isaac 강화학습 | native pose/속도·고정 경로를 사용하는 Q-learning, 9.342m 경로와 정지·여러 시작 방향 평가 | 제한된 native SIM 성과. 카메라는 기록용이며 센서 기반 Gazebo/Fleet·실물 수용과 별도. 기준선도 완주해 성능 개선 수용은 미입증 |

근거: [E6, E9]. 두 경로를 폐기하자는 판단이 아니다. 첫 제품 수용을 위해 세 가지 학습 방식을 동시에 완성할 필요가 없다는 우선순위 제안이다.

## 6. 완료까지의 권장 작업 순서

아래 P0/P1/P2는 작업 의존성과 첫 운영 경로의 완성에 따른 권장 순서이며 기존 backlog나 공식 안전 심각도 분류를 바꾸지 않는다. 담당은 사람 이름 대신 기존 소유 영역으로 적었다.

| 순서 | 작업 | 담당 영역 | 선행 조건 | 완료 판정 산출물 |
|---|---|---|---|---|
| P0-1 | 첫 수용 범위와 버전 고정 | 제품/운영 + 각 owner | 없음 | 주행 방식, 암 경로, 장치·지도·보정·source/model/data revision, 제외 기능, 성공 기준을 적은 1장 |
| P0-2 | drivable 정체·도착 실패 진단 | Drive/인식/CORE + Fleet 결과 | 실패 실행·원본 관측 | 입력→후보→최종 출력의 실패 trace와 원인 검증. 한 프레임 추측으로 종결하지 않음 |
| P0-3 | 독립 평가 자료 적격화 | 모델 PC/curation·evaluation | 정답 의미 고정 | 촬영 세션 기준 분리·예약, 승인 정답, 출처 manifest |
| P0-4 | 첫 설치본 확보 | deploy/운영 | 수용할 revision | 적격 이미지/payload·서명·보정·모델의 설치 목록과 검증 |
| P1-1 | 단일 로봇 주행 종단 수용 | Drive/CORE/Fleet | P0-1·2, 평가/승격 조건 | 같은 버전 반복 완주·거리·정지·경로 검사, 실패 포함 결과표 |
| P1-2 | 실제 시연 학습 모델 확보 | OMX curation/training/evaluation | 암 경로·rig·보정 | 독립 평가와 별도 재적재, 기준선 비교, hash 고정 산출물 |
| P1-3 | 암 학습 SIM 과제 수용 | robot execution/OMX/CORE | P1-2 | 실제 모델로 과제 수행·철회·HOLD·재시작 거절과 목표 증거 |
| P1-4 | 장치 설치·첫 부팅·rollback | deploy + 장치 owner | P0-4 | 실제 매체·서비스·graph·업데이트·복귀 기록 |
| P1-5 | 실제 장치 과제·Fleet 종결 | CORE/OMX + Fleet/운영 | 각 장치 수용 및 승인 | 요청→실제 결과→원장 종결·자원 회수, 단절·취소·재시작 포함 |
| P2-1 | 모델 제공자·그림자 수용 | Decision/AI PC/모델 PC | 독립 사건 정답·실제 격리 | 고정 profile 실행, 품질·비용·timeout·기권, 기존 규칙 대비 결과 |
| P2-2 | 실패 환류 1회 완주 | learning/Decision/Fleet | 실행 실패와 원본 관측 | 실패→검수→다음 후보→독립 평가→승인→적용/rollback 추적 |
| P2-3 | 다중 장치·신호·Cell 확장 | Fleet/각 execution owner | 단일 경로 수용 | 경로별 동시성·점유·중단·물리 목표 증거 |

자료·학습 준비와 배포 이미지 준비는 독립적으로 진행할 수 있다. 실제 주행·암 활성화는 각 경로의 기존 승인·보정·정지 관문을 통과한 뒤 수행해야 한다. 이 보고서 자체는 활성화 승인이 아니다.

예상 소요 일수는 제시하지 않는다. 재현 가능한 정체 원인, 적격 정답 확보량, 최신 이미지 확보 상태, 실물 과제 계약이 확정되지 않아 일정 숫자를 붙일 근거가 부족하다.

## 7. 다음 완료 보고서의 필수 항목

축마다 아래 항목을 갖춘 하나의 수용 기록으로 완료를 선언한다. 성공 사례만 모으거나 서로 다른 SHA의 부분 통과를 합쳐 전체 통과로 만들지 않는다.

1. **범위:** 장치·과제·운영 조건·제외 경로와 사전에 정한 성공/중단 기준.
2. **버전:** source SHA, 실제 설치 revision, model/processor hash, dataset/split, 지도·rig·보정.
3. **입력과 권한:** 실제 입력 출처, 승인 주체, admission/lease/attempt, 최종 execution owner.
4. **검증:** 실행 명령·환경·시험 선택, passed/failed/skipped, 원시 로그 또는 receipt와 무결성 결속.
5. **실제 결과:** 과제 성공·실패·중단의 분모, 거리·정지·물체 상태 등 독립 목표 증거, runtime 모델 사용과 지연.
6. **장애와 환류:** 취소·단절·재시작·자원 회수·rollback, 실패가 다음 검수와 후보 평가로 돌아간 기록.

새 수용 기준의 반복 횟수·허용 오차·품질 하한은 실제 과제 계약에 맞춰 **실행 전에** 확정한다. 이 보고서에서 임의의 숫자를 새 공식 관문으로 지정하지 않았다.

## 8. 근거 목록

링크는 이 보고서 위치 기준이다. 줄 번호는 조사 시점 기준이며 후속 변경으로 이동할 수 있다.

| ID | 근거 | 이번 평가에서 사용한 범위 |
|---|---|---|
| E1 | [전체 실행 흐름 연결 점검](../plans/2026-10-15-runtime-pipeline-closure.md) | 16–29행의 14개 흐름, 원격 회귀·자원 close 및 남은 입력 기록 |
| E2 | [drivable v2 재점검](../validation/pinky-drivable-v2-recheck-2026-10-19/session-report.md) | 23–44행 r51a/r51b 차이, 55–81행 최신 별도 워크트리 실행·stall·실제 모델 소비. 원시 로그는 이번에 재계산하지 않음 |
| E3 | [OMX SIM 종단 검증](../validation/omx-policy-chain-2026-10-19/result.md), [runner receipt](../validation/omx-policy-chain-2026-10-19/runner-receipt.json), [native receipt](../validation/omx-policy-chain-2026-10-19/native-receipt.json) | 66–83행 이동·철회·종료, 179–182행 고정 SIM 범위. JSON을 직접 읽음. runner 기록은 agent-recorded completion이며 장치 발급 attestation이 아님 |
| E4 | [Fleet 실행 완료 계획](../plans/2026-10-12-fleet-pipeline-complete.md) | 기존 경로와 receipt·종결·재시작 완료 기준. 계획 자체를 실행 성공 증거로 사용하지 않음 |
| E5 | [기존 drivable 검수·원본 출처 감사](../validation/drivable-reviewed-desktop-2026-10-11.md) | 63–77행 upstream split 대조, 108행 이후 평가 승인·출처 한계 |
| E6 | [암·주행 학습 파이프라인 기존 평가](2026-10-19-learning-pipelines-status.md) | 직접 경로·학습 연구·기존 자료의 상세 증거 링크. 플랫폼 SIM lease 미연결 설명은 E3으로 갱신 |
| E7 | [Decision 통합 검증](../validation/decision-deliberation-2026-10-12/result.md), [호스트 admission](../validation/deliberation-host-admission-2026-10-12/result.md), [후속 host runner](../validation/pinky-deliberation-host-runner-2026-10-12b/result.md) | 소스 회귀와 실제 격리·제공자·현장 수용의 구분 |
| E8 | [Pinky SD 준비 실행 기록](../plans/2026-10-18-pinky-sd-ready.md) | 호스트 시험, fixture 범위, 당시 이미지 확보 제약, 미완료 실물 단계 |
| E9 | [Isaac native RL 검증](../validation/isaac-map-rl-2026-10-11/result.md) | 18–31행 관측·기준선·학습 평가, 39–68행 재시험·카메라·범위 |
| E10 | [최신 OMX chain 계획](../plans/2026-10-19-omx-policy-chain.md), [설계](../plans/2026-10-19-omx-policy-chain-design.md) | 기존 API·SIM 전용·lease·HOLD 경계와 최신 구현 맥락 |
| E11 | [모듈 gate 집계](../../STATUS.md) | 기존 SOURCE/LOCAL과 ARTIFACT/DEVICE/FIELD 차이. 과거 last_verified를 최신 재시험으로 취급하지 않음 |
| E12 | [World MapPose 구현](../../operations/world/src/rosy/world/state/projections/map_pose.py) | 21–23행 pin/odom, 385–396행 bridged·DEGRADED 판정 |
| E13 | [Fleet composition](../../operations/fleet/fleet/server/app.py), [Task 결과 원장](../../operations/fleet/fleet/server/ledger/task_results.py) | 현재 연결 진입점과 attempt 상관관계 코드의 제한적 확인 |
| E14 | [검수 학습 연결](../../learning/training/perception/review_pipeline.py), [전달·rollback](../../learning/registry/perception/deliver.py) | prepare의 승인 mask 검사, 출처 문맥, shadow/paint 및 rollback 구분 |
| E15 | [ACT 학습·별도 재적재·평가](../../learning/training/omx/native_cycle.py), [SIM lease 소비기](../../middleware/robot_execution/local/src/rosy/execution/local/policy_lease.py) | 현재 도구·소비기 존재와 학습 산출물/권한 결속의 구현 맥락 |

## 9. 조사 한계와 남는 위험

이 보고서는 현재 소스의 일부 핵심 경로와 보존 검증 기록을 대조한 완성도 평가다. 모든 활성 워크트리, 원시 실행 로그, 실물 설치본, 최신 외부 artifact와 제공자 상태를 전수 재검증한 보고서는 아니다. 원시 로그 hash 전부를 이번에 다시 계산하지 않았으며 기존 보고서의 무결성 확인을 이번 검증으로 재표기하지 않았다.

가장 큰 판단 위험은 **한 번의 SIM 성공을 반복 가능한 실물 운영 완료로 올리거나, 과거 HOLD를 근거로 최신 구현과 실행 성과를 지우는 것**이다. 다음 실행은 P0-1의 수용 범위를 먼저 고정하고, 주행 정체 진단·독립 평가 자료·적격 설치본 확보를 진행하는 것이 가장 근거 있는 순서다.
