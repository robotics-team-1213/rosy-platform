# 동일 모델 접촉 관측: 손가락–테이블 접촉, 정책 HOLD

2026-10-24, [접촉 진단 코드·SDK 검증](../omx-policy-contact-diagnostic-2026-10-24/result.md) 뒤 수행한 별도 단일 관측이다. [앞선 추종 HOLD](../omx-policy-tracking-after-admission-2026-10-24/result.md)는 보존한다. 접촉을 실제 관측했으며 실패 인과·정책 품질·실물 수용을 확정하지 않는다.

- runtime commit `22081a48dafbc1e6a223a4047222153947aa06a6`의 로컬 main 착지·원격 검사·실제 SDK 확인 후 시작했다. 같은 모델 sha256: `30bba42551e85be5007d45fcef6a7e36268bad711d8bd85905ad383113cc1326`, 데이터 sha256: `9233e3c239561670ad21dd7791526561abde3c801bb4551f8df40c96c6ac3503`를 사용했다.
- prospective manifest SHA256 `b6e2bcebe0310a4d5518b8cf5919ef84e633ec3a6462bd0d1bd23dcaca1e07c7`, wrapper SHA256 `80032a23468c3defade5818095b145a47d8ea3e79a8ce660aa5f2cf72c8298a6`. 실행 전 독립 검토와72개 실제 입력 바이트·9개 canonical Git blob/main 일치 검사를 통과했다. 기존 transport 두 파일 변경은 새 manifest에 명시하고 원래 manifest·HOLD·driver는 바꾸지 않았다.
- 최대 calibration1회+접촉 관측1회, 자동 재시도/optimizer/formal/실물 권한0. 시작 전 여유 조건8CPU·12GiB와 실제 quota를 구분한다. 관측 서비스의 종료 후 systemd 속성은 CPUQuota4CPU/MemoryMax4GiB/Swap0이며 내부 기한600초를 유지했다. 정상 종료한 calibration unit은 이미 회수돼 현재 속성의 infinity를 실행 당시 제한으로 해석하지 않는다. 명령 소유자·JTC 허용치·freshness·lease·WAL/FULL을 유지했다. 센서 계측에 따른 시간 영향이 있어 앞 실행과 성능 비교를 하지 않는다.
- 원격 manifest의 설치 의존85,872개 해시는 앞 진단과 같다. policy 입력7개는 상대 경로로 비교했고 weights/config/normalization/offline report/artifact의5개 바이트가 같다. 새 calibration receipt와 campaign만 다르다. 파생 world는 camera base와 비교해 Contact plugin·센서2개 외 DOM이 같다.

## 실제 종료·회수

| 실행 | 결과 | 원본 바이트 대조 | 추종 표본 |
|---|---|---|---|
| calibration `c3893b407b32` | native0/PASS | 96파일, 108,480,105bytes | 299 |
| contact `33ec34fd23eb` | native1/HOLD | 264파일, 134,631,711bytes | 2,462 |

coordinator 종료0은 수집 완료다. 두 actor 모두 PID0·빈/부재 cgroup·budget lock/reservation 부재를 확인했다. 관측 실행의 remaining_groups=[]/verified_absent=true이며 수집기 최종 기록도 검증됐다. 추가 실행은 하지 않았다.

SQLite integrity 검사를 통과했고172 intents/172 native 수락/172 terminal 중171개 status4/result0, 마지막 status6/result−5다. 마지막 command `6efb88d1-445c-496c-b257-f81e91e9986a`, goal `36785eba-54cc-4d89-9457-8ad3ae67d20b`는 DB·step·native event에서 일치한다. JTC 로그의 zero-based index3/4는 joint4/joint5, 오차−0.050343/−0.060525rad와 허용치0.02rad, goal-time 초과1.010s를 기록했다. admission_rejection/camera_error는null, worker_errors=[], owner_final=hold다. lift0.000034131m·불완전 관측 success=false이며 작업 성공은 아니다.

## 접촉과 추종

두 채널은 각각154,809개 메시지를 검증하고3,254개씩 저장했다(합6,508개). invalid0·truncated=false, 두 positive control 확인. raw receipt 최대 공백은 약504.6ms다. 10Hz 저장 표본은 연속 관측이나 전체 접촉 최대치를 뜻하지 않는다. 발행되지 않은 구간은 unknown이다.

table 채널에 `omx_f::link6::link6_collision`, `omx_f::link7::link7_collision`과 `table::top::collision`의 접촉 보고가 각각315개 저장됐다. 첫 저장 보고는 terminal 수신보다30.855333s 앞서며 실제 접촉 시작 시각으로 해석하지 않는다. 마지막 goal 수락→terminal 수신3.750481s 구간에는 각각37개다. 저장된 **개별 point wrench의 force norm** 최대는 link6 약24.694, link7 약63.973(발행 원본 단위)이며 합력·연속 최대·실물 힘이 아니다. frame/body 필드는 변환 없이 보존했다.

같은 마지막 goal 구간의19개 추종 표본은 최종 후보 reference와 일치한다. 마지막 일치 표본은 terminal 수신 약127.698ms 전이며 joint4/5 position error는−0.049005/−0.058699rad다. controller abort 후 client terminal 수신 전에 reference가 바뀔 수 있으므로 최후 표본의 작은 오차를 성공 근거로 쓰지 않는다. 수신 시각·reference·접촉의 상관은 native 실행 인과 증명이 아니다. link6–물체 첫 저장 보고는 terminal 수신114.284ms 전, link7–물체는702.857ms 후여서 물체 접촉을 abort 원인으로 단정할 수 없다.

## 보존·다음 확인

raw와 재현 분석은 `C:/DevTemp/learning-execution-20261023/contact-policy-observation-20261024/`에 보존한다. 원본·카메라·DB·주소는 저장소에 넣지 않는다. 최종 ledger sha256: `99b29f684de68f896e82501d764b8b46537c259285312ea9787b7c8b89ad36de`, 관측 archive sha256: `cb47f0992d7e57d00d247dc416bb6971a6dbe2619f0ebfbf2771eb57febbf851`, 접촉 sha256: `9cc96ac47e011d924408a86b95333e9dbf11ffa2674614c4e8fa61a1aa992670`, 추종 sha256: `cd57c24af427a1100852266830d0cb226dcac9000e0880d0942b5bd4c48a3366`, 재현 분석 JSON sha256: `87c4db8ba9aab8b19d16de099eb93d0751569102ac28abf664f811a963038390`. 원본 archive/map/전체 바이트·DB·수치·파생 world·종료를 독립 대조했다.

앞선 nominal URDF/STL의 정적 분석은 실제 runtime 충돌 근거를 대신하지 못했다. 다음은 이번 실제 관측 자세를 사용해 launch가 만드는 collision 형상·pose·engine margin을 대조하고, 명목 분석에 포함되지 않은 조건을 확인하는 것이다. 직접 접촉 증거는 확보했지만 원인 조치·재학습·승격은 아직 수행하지 않았다. CE: 미해결 — 원인과 해결이 검증되기 전 해결 교훈으로 승격하지 않는다.
