# 공유 store의 신규 발행 권한

D-434 모델 PC에서 producer와 model-watch의 계정이 다른 경우를 다룬다.
기존 저장소 스냅샷 반입 뒤에도 새 모델·데이터셋·고정 평가 세트의 권한이
감시 계정의 접근을 막는 문제를 수정했다. 기존 setgid POSIX 대상 디렉터리가
공유 발행의 명시적 조건이며 publisher는 그 그룹의 구성원이어야 한다.

새 부모·artifact 디렉터리는 2770, 새 데이터 파일과 READY는 0640으로 맞춘다.
원본 파일 권한·내용 해시·이미 발행된 버전은 바꾸지 않는다. 비공유 store와
Windows는 기존 권한 동작을 유지한다. 서비스와 producer의 그룹 등록 자체는
관리자 작업이며 이 소스 변경이 대신 수행하지 않는다.

`Store.put_dataset`, `handover.package`, GPU `train_job.publish_ready`,
`build_auto_dataset`의 dataset/evalset 발행을 연결했다. rename 또는 READY 전에
신규 파일 권한을 준비한다. GPU READY write 뒤 chmod 직전에 중단되면 재시도가
동일 digest를 확인하고 자기 inbox READY의 읽기 권한을 마무리한다.

독립 리뷰에서 대상 `.part` symlink에 copy가 먼저 쓰는 결함, 상위 ancestor link를
놓치는 결함, READY chmod 중단 후 권한을 복구하지 않는 결함이 발견됐다.
Linux fixture에서 각각 재현한 뒤 복사 전 대상·상위 경로의 link 거절,
검사한 regular partial 제거 후 exclusive 새 파일 작성, 재시도 chmod로 수정했다.
이는 root installer가 아니라 비특권 producer 코드다. 그룹은 신뢰된 발행자와
서비스에만 등록하며 서로 적대적인 동시 writer를 격리하는 보안 경계로 주장하지 않는다.

실제 모델 PC의 별도 `shared-publication-v1/source`에서 시험했다.
최초 model fixture는 클래스 1개로 잘못 구성해 두 검사가 준비 단계에서 실패했다.
이를 수정한 RED는 4개의 실제 권한/link 실패였다. eval 별도 RED 1건,
리뷰 link 회귀 RED 2건, READY 중단 회귀 RED 1건을 확인했다.
수정된 5개 suite는 최종 59 passed, 0 skipped였다. 시험에는 umask 077,
source 0700/0600, 원본 보존, READY digest, 링크 외부 파일 무변경과 중단 재시도를 포함한다.

수정본 독립 HOST 리뷰는 44 passed, 8 skipped로 승인됐다. POSIX 회귀는 Windows에서
생략됐다. 실제 Linux 검증 범위를 dataset build/publish와 watcher inbox 연계까지
넓힌 최종 9개 suite는 exit 0, 127 passed, 0 skipped였다. 실행 전후 다섯 source/test
파일의 SHA가 같으며 비공개 결과 JSON과 로그를 별도로 보존했다.
다섯 native 파일의 SHA는 현재 로컬 후보와 일치했다. D-436 affected HOST 검사는
486 passed, 21 skipped, 19 warnings였고 경고는 기존 last_verified 지연이다.
lint는 0 errors, 추적된 새 파일을 포함한 secret/provenance 검사는 19 passed였다.

실제 다른 UID의 서비스 접근·systemd sandbox·상시 producer 설정 연결은 미검증이다.
설치 후보의 고정 소스 archive도 이 변경을 포함하도록 새로 준비·검토해야 한다.
기존 검토 archive를 조용히 바꾸지 않았다. 기존 학습 GPU 환경·실데이터,
로봇 HOLD·pointer·운영 명령은 변경하지 않았다. 인간 라벨과 owner/Fleet 수용도 남았다.

비공개 증거: `X:/DevTemp/rosy-learning-audit-20261004/`의 보고서,
실제 모델 PC의 `shared-publication-*` 격리 fixture와 source. 관리자 설치와
서비스 활성화 없이 수행한 소스 및 Linux 검증이다.
