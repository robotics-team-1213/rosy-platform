# Rosy Learning 키 재발급과 이름 변경 배포

2026-10-20 00:18 KST 기준. 사용자가 기존 키를 다시 발급하고 배포하도록 명시적으로 요청했다.

## 완료한 배포

- 모델 PC의 정상 업데이트 경로로 sequence **30**, source **commit `9bafdf968277191b93171daf4f8740f240e9418e`**를 적용했다. updater 결과 `applied`, pending 없음, failed 목록 비어 있음.
- 기존에 검토하고 원격 검사 **254 passed / 0 skipped / 0 NEW**를 확인한 정확한 커밋이다. 이번에는 소스를 바꾸지 않았다.
- 공식 후보 생성기를 해당 커밋에서 실행했다. 실행별 `core.autocrlf=false`로 archive 바이트를 보존했다. archive SHA-256은 준비된 후보와 같은 `d4413c470c1c7e51a345833bd6c4e3ee8ce01d08e3e51ecca7335a0ab4e46bc3`이다.
- 실제 서명한 manifest SHA-256은 **`e3cb73391dce5f2a2c95d4ba251942b67a19369a4353db49e5086081948c8ebe`**다. 앞서 수동 준비한 미서명 manifest `853a…`와 필드값은 같고 끝 줄바꿈 바이트가 다르다. 최초 교체 시도에서 이전 hash 기대값 검사가 이를 감지해 설정 변경 전에 중단했다. 공식 생성 파일을 독립적으로 재계산해 기대값을 바로잡은 뒤 진행했다.
- 환경 지문은 기존과 같은 commit `97fab2525162e8b93ae730e6c1426ca7c84e07afc0821856ba4e31dccb1412eb`다. 기존 업데이트 서비스의 작업·GPU·환경·import·실제 CLI 검사와 동결 게이트를 통과했다. 패키지나 GPU 환경을 바꾸지 않았다.
- 기존 review follower를 실행해 `model-code-30-9bafdf968277` 검수 UI 릴리스를 활성화했다. 검수 서비스는 active/running, updater와 review follower 타이머 모두 active다.
- 독립 검토 `names_review`가 실제 신뢰 설정·공개 키 지문·sequence 30·전체 소스 SHA·manifest·READY·서비스·타이머·상태 경로와 아래 네 화면을 다시 확인했다. 중요한 발견 사항 없음. 서명 변조 검사와 과거 inbox 보존은 실행 담당자의 확인이며 독립 검토에서 반복하지 않았다.

| 실제 경로 | 응답 | 실제 제목 |
| --- | --- | --- |
| `/` | 200 | Rosy Learning — 객체 검수 |
| `/pixels` | 200 | Rosy Learning — 픽셀 검수 |
| `/catalog` | 200 | Rosy Learning — 자료 등록 |
| `/learning` | 200 | Rosy Learning — 학습 작업 |

실제 실행 프로세스의 `--state`는 기존 `/home/rosy/rosy-ml/review-v13-drivable/state`를 유지한다. 사람 라벨 수정·학습 시작·모델 승격·로봇 동작은 수행하지 않았다. 위 화면 검사는 읽기 전용 HTTP 응답·제목 확인이며 새 브라우저 조작 시험이나 모델 정확도 평가가 아니다.

## 새 서명 키와 복구 자료

- 전용 Ed25519 키 ID: **`model-code-20261020`**. 다른 역할의 키를 재사용하지 않았다.
- 운영자 PC 키 폴더: `C:/Users/SERIGGG/AppData/Local/rosy/model-code-signing/model-code-20261020/`. `private.pem`은 현 Windows 사용자만 접근하도록 상속을 끊은 폴더에 생성했다. 개인 키는 출력하거나 모델 PC로 전송하지 않았다. `public.pem`만 모델 PC로 보냈다.
- 공개 키 파일 SHA-256: `0c1cccff151f1cd6871ed4c972d1fff008369fd0bfeb314aaea5f25fa307a1c7`.
- 모델 PC 설정 `~/.config/rosy/model-code.json`의 `key_id`와 `public_key`만 바꿨다. 새 공개 키는 `~/.local/share/rosy/model-code/keys/model-code-20261020.pub.pem`이다.
- 교체 동안 기존 updater 타이머를 잠시 정지하고 service inactive와 기존 exclusive `work.lock`을 확인했다. 잠금 안에서 기존 sequence 29·소스·공개 키 hash·HOLD 부재, 새 서명·archive·환경을 재검증했다. 설정은 원자적으로 교체하고 타이머의 기존 활성 상태를 복구했다.
- 기존 설정 백업·교체 receipt: `~/.local/share/rosy/model-code/key-rotation-backups/model-code-20261020/`. 기존 공개 키 `~/.local/share/rosy/model-code/public-key.pem`도 그대로 보존했으며 hash 일치를 확인했다. 분실된 기존 개인 키를 복구한 것은 아니다.
- 기존 키의 서명 검증을 통과한 sequence 29 이하 inbox 28개는 `~/.local/share/rosy/model-code/retired-inbox/model-code-20261020/`로 보존했다. 과거 활성 릴리스·라벨·데이터는 삭제하지 않았다. 새 키로 과거 서명을 반복 거절하지 않도록 입력 폴더에서 분리했다.
- 새 후보는 archive·manifest·signature를 먼저 전송하고 키 등록 뒤 **READY를 마지막에** 전송했다. 설치된 서명 검증기로 새 서명 수용, 변조 manifest 거절, 이전 키 서명 거절을 모두 확인했다.
- 로컬 서명 후보: `C:/Users/SERIGGG/AppData/Local/Temp/rosy-learning-naming-20261020/signed-sequence-30/`. 일회성 교체 절차: 같은 상위 폴더의 `rotate_model_key.py`. 상태를 고정해 재실행을 거절하도록 작성한 작업 기록이며 반복 운영용 도구가 아니다.

## 다른 앱

Fleet·Cell은 [10월 19일 배포 기록](../rosy-app-deployment-2026-10-19/result.md)의 `38f0c452e410` 버전으로 이미 배포했다. 이번 작업에서는 다시 배포하지 않았다.

Vault·Device·Games의 이름 변경은 병합되어 있지만 실제 배포 대상과 운영 설정이 여전히 확인되지 않았다. 이 앱들은 이번 키 재발급으로 배포된 것이 아니다. Vault·Device의 대상 PC/서버와 운영 설정, Games의 운영 노트북과 경기 설정 경로가 있어야 이어서 적용할 수 있다.
