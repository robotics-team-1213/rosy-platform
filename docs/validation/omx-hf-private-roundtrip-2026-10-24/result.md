# OMX SIM 데이터의 실제 private Hugging Face 왕복 검증

`robotteam/rosy-omx-sim` private dataset을 만들고 실제 업로드한 고정 커밋
commit `5a7a5952030e57424349b17199fe1b6d4b3e6da9`에서 전체 파일을 내려받아 검증했다.
대상은 SIM scripted-teacher 에피소드1개이며 전체 학습 코호트·사람 시연·정책 성공
수용을 뜻하지 않는다. 기존 정책 품질은 HOLD다. 로컬 main 기록 착지는 별도 상태다.

## 입력과 실제 수용 범위

소스 commit `73fc8b2b09cbefa6aee22a786ca2b418a8e979b8`의
`hub_sync.prepare_bundle/upload_bundle`과 `verify_export`를 사용했다.
사용자 인증은 모델 PC의 전용 학습 환경에서 확인했으며 robotteam은 개인 namespace다.
토큰 값은 출력·전송 묶음·기록에 넣지 않았다.

원본은 에피소드 `b197666a-eb95-49eb-a1dc-130e4f5117ea`의1612파일,
35537382bytes,1587PNG프레임, LeRobot v3 데이터·영상·관절·이벤트·SIM 증거다.
원본 전체 SHA를 검토 manifest와 대조한 뒤 별도 복사본에 SIM/research/HOLD를 밝힌
README 카드만 추가했다. 최종1613파일 전체를 고정 커밋에서 내려받아 SHA를 비교했다.
LeRobot0.4.4 reader는1587프레임과 `sim_ground_truth` 판정을 재확인했으며
video_mean_absolute_error_max는1.6412543058395386이다.

대상 private 여부,40자 commit SHA와 빈 초기 파일 목록을 검증했다.
초기 파일 목록은 최대 `.gitattributes`만 허용했다. 목록 검사는 캡처한 불변 SHA에
고정하고 실제 commit parent도 그 SHA로 제한했다.
다른 head는 위임 전에 거절하고 이후 경합은 Hub CAS로 거절한다.
원본→복사본 사이에도 전 파일 SHA 일치를 요구했다.
텍스트22파일 scanner 후보는 무결성 해시·Git SHA·소스 경로/파일명으로 분류했다.
자격증명 대입·개인키 finding은 없었다. 원본 긴 JSON 행 scanner timeout은
JSON을 내부에서 들여쓰기한 뒤 같은 scanner로 완료했으며 값은 출력하지 않았다.

## 실패 보존과 읽기 전용 복구

첫 official durable SDK job은 실제 업로드 커밋과 upload.json을 남긴 뒤 다운로드의
HfHubHTTPError429로 종료됐다. 진행 로그는1605/1613이었으나 진행 카운터를 실제
저장 파일 수로 해석하지 않았다. terminal rc1, scope inactive, 빈 cgroup과
lock/reservation 해제를 확인했다. 성공 영수증은 없었다.

첫 로컬 회수는 tar.extractall에서296자 HF 임시 cache 경로의 FileNotFoundError가
발생해 중단됐다. 원격 산출물은 보존됐다. 긴 경로 제약에 부합하는 실패이며
OS 전체 경로 설정이나 모든 발생 원인을 별도 입증한 것은 아니다.
완전한 payload·upload.json·부분 readback cache를 별도 원격 경로에 보존하고
1613payload SHA와 manifest 일치를 재검사했다. 최초 작업은 재제출하지 않았다.

429 관측 뒤5분 이상 기다리고 별도 SDK job에서 같은 manifest/revision을 재개했다.
ReadOnlyApi가 create_repo/create_commit를 거절하며 downloader도 그 revision만
허용한다. max_workers1과 기존 cache를 사용했다. 이 설정과 대기 시간이 보편적인
429 원인·해결임을 입증하지는 않는다. 새 저장소 쓰기0으로 bytes/reader 검증에
성공했다. 회수 경로는 `C:/DevTemp/hf-r2-20261024`로 줄였다.
복구 원격 terminal rc0, scope inactive, 빈 cgroup, lock/reservation 해제를 확인했다.
짧은 경로의 공식 coordinator도 EXIT0으로 끝나 전체 로컬 회수를 완료했다.
회수한 payload/readback 각각1613파일35538112bytes를 manifest와 독립적으로
다시 해시 비교했다. upload/receipt/result의 revision과 파일 목록이 같고,
receipt 해시는 result와, result 내용은 종료 관측과 일치한다.

두 실행은 official remote_sim durable transport의 model8CPU/6GiB/20분 제한 안에서
전용 SDK를 사용했다. 실행 scope의 실제8s CPUQuota와6442450944 MemoryMax를 읽었다.
export 요구9패키지와 SciPy 버전 및 NumPy/PIL/SciPy import 위치를 확인했다.
공유 venv를 변경하지 않고 실행별 NumPy2.2.6/Pillow12.3.0/SciPy1.15.3 prefix를 썼다.
로봇 명령·physics actor·optimizer step·정책 추론은 모두0이다.
초기 프로토콜2건, 복구 프로토콜2건의 독립 검토를 통과했다.
actor-free 자체 검사는 초기3+3개, 복구2+3개가 통과했다.

## 결속 산출물

외부 BASE: `C:/DevTemp/learning-execution-20261023/`.
초기 root는 `hf-private-roundtrip-20261024/`, 복구 root는
`hf-readback-recovery-20261024/`, 복구 출력은 `C:/DevTemp/hf-r2-20261024/out/`이다.

| 산출물 | SHA-256 |
|---|---|
| 원본 manifest | `cfae241a76ce06129eeee04247b0782c7ebc66d9b465d2317d302e17a92cd949` |
| 최종 bundle manifest | `7cb1a18979089476e1f9f34ab1d8db6899d5a2cc566acbc0a487b8dfc1aff329` |
| README 카드 | `d79f12e8a44bb436c72c15f5b8879f62cc184bd7fa54e902b7347ee3739f2d1b` |
| upload.json | `4bbec4ee7fe94e3c5fc1501822efb66cd1426ccf3c1825f819efc909f27f21f1` |
| 복구 receipt.json | `c6aacd162090c7b0db39a56398ae80a170b8d7c023800226a17cd21c94334e22` |
| 초기 worker.py | `f5a8bfc0d3a17bc09a56e1b9e5e59196e07cfdb21c93389840deb067459065d9` |
| 초기 run.py | `19c0706fc889bdac81207be56f1b0e9881e153287efbdc2216299ca7141d8d08` |
| 복구 worker.py | `2d307d5db7f8f5851202caac2cb8b858bd23188fe61160cdb73306702f0fcfba` |
| 복구 run.py | `b6ecf9638305bdd0b7f1814ee42f4bdd12e2b251f889f5cf5b93c3e353921d58` |
| 초기 closure.json | `714f831e66efc74a6443a17bb5c6c2d00d13be8f0dfb415f7315714b7ebe10dd` |
| 초기 initial-metadata.json | `375de490f71ed449865470e64aa57d3e390db6461264ad4d8492fe8bf726c718` |
| 복구 closure.json | `ad7017f5b1b022fc8f01771a392de20765aa3536269ac9afd3a069bac050c90d` |
| 복구 out/result.json | `80762d3b13c3bde9fd204985c584efbe1a7bdd7bf4e60cd8362b45019d0bda5c` |
| 복구 local-verification.json | `6d20b1657f54661044c33a77e3ed22d74a45e66093b0646656faa00accbb91d0` |

## 남은 파이프라인

기존10k-step 실제 모델5파일45384876bytes의 해시를 검증하고 카드가 포함된6파일
model bundle을 offline 준비했다. `hf-model-prepare-20261024/bundle/manifest.json`
sha256: `56440629fd060fef9a9e11670efc447cb9cffe9bcbf9736c890959fc3351766b`다.
대상 후보 `robotteam/rosy-omx-policy`는 아직 생성·업로드하지 않았다.
실제 Hub 고정 모델 다운로드와 fresh-process ACTInference 재적재는 별도 필요하다.
native_cycle 형식의 checkpoint가 아니므로 그 verify 소비자로 대체하지 않는다.

관절 정책의 SIM task 성공·독립 반복 평가,12관절 양팔 실행 owner 수용,
실물 데이터/사람 라벨 수용 및 주행 learned adapter는 별도로 남아 있다.
데이터 Hub 전송 성공만으로 이 항목들을 완료 처리하지 않는다.
