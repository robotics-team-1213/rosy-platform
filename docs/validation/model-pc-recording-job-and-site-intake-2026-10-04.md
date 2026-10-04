# 실제 모델 PC 작업과 관제 PC intake

2026-10-04, 소스 commit `2a2900dfb`를 별도 경로에 고정했다.
새 녹화나 로봇 명령 없이 기존 5세션을 처리했다. 자동 라벨 데이터이며 사람 검수
정답으로 간주하지 않는다. 어두운 장면 개선은 사용자 결정으로 이번 범위에서 제외한다.

## 모델 PC

녹화 출처 catalog → 자동 라벨 → immutable dataset → GPU 학습 → ONNX → intake →
READY를 실제 실행했다. 데이터셋 404프레임(train 322 / val 82), 5세션이며
content hash를 재확인했다. 고정 평가 세트 126프레임/2세션도 최신 read_eval_set
검사를 통과했고 학습과 평가의 촬영 세션은 겹치지 않는다.

RTX 5080 Laptop, Torch 2.11.0+cu128, CUDA 12.8에서 base8/enhanced,
seed 42708, 30 epochs를 실행했다. best epoch 26, val mIoU 0.759.
고정 평가 lane_line IoU 0.591466, mIoU 0.459755, drivable IoU 0.018888이다.
정지선·횡단보도는 train/val 정답 픽셀이 모두 0이다. 따라서 이번 모델이
횡단보도 오분류를 해결했거나 회전교차로 진입 판단에 적합하다는 증거는 없다.

처음에는 분리된 intake 출력 경로에 기존 최고 모델 이력이 없어 상대 성능 검사가
빠졌다. 이 실행의 종료 코드 0과 READY 기록은 이 한계를 포함한다. 기존 canonical
intake 이력을 사용해 재검사했고, 최고 모델 mIoU 0.518525 대비 허용 하락 0.01을
초과하여 exit 1 / fail이었다. 후보 `lane-seg-20261004-6b4e7c3c`를 rejected로
이동했다. 기존 작업 resume도 exit 1이며 부모와 자식 outcome은 rejected다.
다음 작업용 설정은 canonical intake 경로를 사용하도록 별도로 준비했다.

## 관제 PC

같은 소스와 독립 venv를 준비했다. Python 3.14, ONNX Runtime 1.30.0,
ONNX 1.23.1, OpenCV 5.0.0.93의 import와 pip check가 통과했다.
실제 해결된 wheel 버전/hash를 requirements.lock에 보존했다.

19개 원본 재생 영상, 학습·평가 데이터와 후보 모델을 전송했다. archive와 모든
1,617개 파일의 hash/크기 및 manifest 전체 coverage를 수신 후 확인했다.
기존 handover로 READY를 생성하고 관제 PC에서 intake를 실행해 기존 최고 모델과
비교했다. 모델 PC와 같은 fail 결과이며 store의 rejected에 보관했다.
래퍼 exit 0은 거절 처리 완료를 뜻하고 모델 intake exit는 1이다.
로봇 delivery는 호출하지 않았다.

## 상시화와 인계

실제 관제 PC에 system model-watch service/timer는 없다. sudo 비대화형 인증은
실패했다. 관리자 설치 스크립트와 installer dry-run(exit 0)을 준비했으며, 설치
스크립트 bash 문법 검사도 통과했다. 실제 관리자 설치·timer 활성화는 미실행이다.
사용자는 현장 관리자에게 실행 요청하는 방식을 선택했다. 수신자/채널은 미정이다.
설치 후에도 전용 site key 등록, host key 고정, 로봇 HOLD 확인, 설정·doctor가 필요하다.

제어 PC에 모델 PC/관제 PC별 전용 SSH 키와 별칭을 등록했다. 기존 authorized_keys
bytes와 기존 config를 보존했다. 모델 PC는 LAN의 일반 OpenSSH에서 전용 공개키의
fingerprint와 Server accepts key를 확인했고 접속 exit 0이다. 관제 PC의 별칭 접속도
exit 0이지만 Tailscale SSH 인증이며 일반 OpenSSH 서버는 미설치다. 관제 PC 전용
키 로그인은 관리자 서버 설치 후 검증해야 한다. SSH 인증은 sudo 인증을 우회하지 않는다.

원본 증거는 X:/DevTemp/rosy-learning-audit-20261004/whole-recording-job-evidence와
site-intake-evidence에 있다. 실제 사람 라벨·새 클래스 평가, 상시 watcher, shadow/rollback,
OMX/Pinky owner 실행·Fleet 결과 및 DEVICE/FIELD 수용은 미완료다.

## 후속 배치 정정

관제의 intake 결과는 당시 별도 재현 증거로 보존한다. 상시 설치 대상은 Accepted
D-434의 모델 PC다. 관제 installer 요청은 실제 system 설치 전에 철회했다.
현재 모델 PC 환경 준비와 남은 실행 단계는
[배치 정정 기록](model-watch-placement-correction-2026-10-04.md)을 따른다.
