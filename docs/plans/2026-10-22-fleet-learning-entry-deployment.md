# 기존 Fleet 이미지에서 Learning 진입을 배포한다

## 검토안 v4

사용자는 하나의 기존 Learning 프로젝트를 Model/AI가 공유하며 여러 종류·여러 개체의 로봇을
학습하는 센터임을 명확히 했다. 최종 진입은 특정 OMX 화면이 아닌 `/learning`이다. D-840의
로봇 종류/개체/참여 그룹/과제/어댑터/실행 호스트 구분을 적용한다. OMX는 첫 구체 경로다.
출판 원본은 별도 개발 main이 아닌 실제 signed site build의 `origin/main`이다. 이력이 다른
개발 줄기는 보존하고 필요한 학습/진입 변경만 운영 원본에 이식한다.

사용자는 개발용 터널과 별도 후보가 아니라 기존 Fleet 솔루션에서 로그인하고 학습할 수
있어야 한다. 구현·시험·운영 접속까지 요청했다. 기존 Fleet/Account 원장·장치 권한과
Model/AI 학습 호스트의 데이터·실행 소유권을 유지한다.

선택한 방식은 기존 Fleet Docker 이미지에 학습 진입 화면을 포함하고, 운영자가 명시한
Model/AI Learning의 보호된 HTTPS 원본으로 이동시키는 것이다. 기존 중앙 Account의 로그인과
프로젝트 권한을 그대로 사용한다. Fleet에 학습기/새 인증 DB를 넣거나 토큰을 URL에 붙이지 않는다.
브라우저는 승인된 공식 Learning 원본을 연다. 개발용 localhost·터널 주소는 설정에서 거절한다.

기존 `/console?view=work`의 작업 하위 탐색에 학습 진입을 둔다. `/console/learning`은
목적과 두 실행 호스트를 안내하고 `/console/learning/model`, `/console/learning/ai`는
고정 서버 설정의 원본 + `/learning`으로만 이동한다. 사용자 입력은 이동 주소가 될 수 없다.
미설정 호스트는 서비스 준비 안내를 표시하고 학습 가능으로 보고하지 않는다.
이들은 웹 문서 경로이며 새 Fleet 장치/원장 API가 아니다.

Fleet의 private `ROSY_LEARNING_APPS_CONFIG` JSON은 model/ai HTTPS origin만 가진다.
알 수 없는 키, 자격·쿼리·fragment·경로·loopback·평문 원본을 거절하고 시작 시 한 번 검증한다.
Compose는 기존 private 설정 마운트와 환경을 통해 전달하며 키·실제 호스트를 Git에 넣지 않는다.
Fleet/Proxy/Vision 기존 서명 후보 빌드·검증·건강/rollback 경로와 실제 이미지 신원을 사용한다.

현재 Model에는 기존 Account 보호 Learning 5개가 있다. 각 origin/project/사용자 권한·라벨 DB를
임의로 다른 앱의 것으로 바꾸지 않는다. 실제 OMX 실행기와 맞는 운영 원본을 확인한 뒤 등록한다.
AI에 보호된 운영 원본이 없으면 먼저 기존 Learning 설치/Account 경로로 준비하며 인증을 끄지 않는다.
UI만 연결해 실물 HIL-SERL, 실제 사용자 인증/HF 동의 완료로 보고하지 않는다.

AI PC에서의 학습은 이번 사용자가 요청한 실험실 오프라인 학습 범위다. D-516의 운영
고정 추론 서비스와 별도 OS 사용자·서비스·가상환경·코드/자료/모델 출력 경로를 사용한다.
학습 사용자는 운영 추론의 승인 모델·설정·자격을 읽거나 바꿀 권한을 받지 않으며 Fleet
원장·장치 API·ROS 권한도 받지 않는다. 학습 산출물의 운영 추론 승격은 기존 독립 평가·승인
경로를 따른다. GPU를 쓰는 경우 운영 추론과 동시에 쓰지 않도록 학습 시작 전 해당 자원의 운영 사용을
확인하고, 사용 중이면 대기한다. 기존 운영 추론을 임의로 중단하거나 재설정하지 않는다.
이 분리와 자원 확인 수단이 확인되지 않으면 AI 학습 연결은 blocked다.

두 호스트는 같은 기존 중앙 Account project_id에 바인딩하되 Account client/audience/callback과
OS 사용자·상태 DB·center root는 호스트별로 유지한다. 공유할 자료는 검수 결과의 불변 버전,
dataset/model revision·파일 hash·과제/참여 그룹/입력 서명 같은 공개 가능한 provenance다.
명시적인 봉인 자료 전달과 수신 검증을 사용하며 개인 토큰·세션·HF 비밀·쓰기 가능한 DB를
복제하지 않는다. 현재 Center는 호스트별 SQLite/파일 원장이며 두 원본 사이의 자동 목록/작업
동기화는 구현하지 않았다. 화면에서도 실행 호스트와 해당 호스트의 작업 범위를 표시한다.
선택할 기존 프로젝트와 두 운영 서비스의 실제 매핑·자원 분리·공유 자료 경로는 아직 확인 전이다.

대안인 Learning 전체를 Fleet 프로세스에 넣는 방식은 기존 HTTP 서버·OAuth callback·정적 경로와
학습 의존성/실행 소유권을 바꾸므로 이번 진입 통합에 불필요하다. 단순 같은 원본 reverse proxy는
Learning의 루트 자산·callback·cookie·공용 자산 충돌을 해결하지 못한다. 전용 신규 공개 포트도
기존 보호 원본이 있는 경우 만들지 않는다.

## 수행과 검증

1. 최신 공용 소스의 중앙 Account·Learning pipeline/SIM/구간 검수를 OMX 기능과 함께 보존한다.
2. 명시 origin 설정·웹 경로·작업 탐색·Compose 배포 전달을 구현한다. 미설정/장애 안내를 제공한다.
3. 원격 HTTP/Chromium에서 정상 이동, 설정 거절, 입력으로 이동 주소 변경 불가, 토큰 비전달,
   미설정 안내, 기존 Fleet 로그인/기존 Learning/모바일 회귀를 확인한다.
4. 등록 전에 각 공식 target의 service/release, project, Account client/audience/callback,
   state root, OMX center 구성·실행기 가용 상태를 private 기록으로 확인한다. 후보 설치기는
   운영 수용 경로로 사용하지 않는다. Model은 기존 D-545/D-446의 서명 코드 설치·업데이트를
   통해 정합 소스와 OMX 구성을 준비한다. 기존 계정/라벨/owner 바인딩은 보존한다.
   AI는 그와 같은 보호된 운영 원본·중앙 client 등록·실제 project 권한을 준비한 뒤 연결한다.
   TLS/DNS·Account 등록·자격·배포 권한이 없으면 해당 host를 blocked로 표시하며 두 호스트
   사용 가능 완료를 선언하지 않는다. 기존 다른 프로젝트의 권한·state를 임의 재사용하지 않는다.
   두 target의 실제 project_id가 같은 기존 프로젝트인지 대조하고, 각 host의 계정·DB·center
   경로와 AI 실험실 격리를 먼저 기록한다. 이름이 같은 프로젝트라는 설명만으로 통과시키지 않는다.
   D-446 후보에는 설치된 controller가 포함되지 않는다. 두 target에 사용하는 신뢰된
   `auto_review_release.py`와 `install_review_release.py`를 검토한 고정 revision의 설치 경로로
   별도 준비하고 파일 hash·서비스/타이머·원복본을 기록한다. 서명 소스 수용 후 해당 서비스의
   실제 ExecStart에 기존 `--collaboration`과 정확한 `--omx-center-config`가 함께 남는지 확인한다.
   학습 Python과 LeRobot/torch 환경은 코드 후보와 별도로 준비·지문 확인한다. 서명 후보 적용만으로
   controller나 환경이 갱신됐다고 보지 않는다. 새 보호 원본을 설치할 기존 운영 설치 경로가 없으면
   이를 먼저 확정하며 `install_learning_center.py`의 별도 loopback 후보로 대체하지 않는다.
5. 커밋/이미지/manifest/서명/실제 Compose 조합을 결속해 후보를 검증한다. 기존
   `deploy/site/rosy_site_autoupdate.py`의 서명 검증·전환·rollback 경로로 실제 운영 stack에
   설치하고 running Fleet image ID/digest, source SHA, signed manifest, effective Compose,
   공식 HTTPS URL, 전환 후 건강과 Fleet→Learning 진입 결과를 남긴다. 후보 빌드만은 미완료다.
6. 실제 권한이 있는 프로젝트 사용자의 보호 OMX 접근, 익명/다른 프로젝트 거절,
   예상 실행기 구성과 project/owner/data 바인딩 보존을 확인한다. 변이 작업은 통제 fixture에서
   검증한다. 실제 사용자 로그인/HF와 현장 학습은 관측한 범위만 보고하며 미실행 항목은 남긴다.
   두 공식 원본의 `/learning` 일반 홈과 동일 project_id를 확인하고, 호스트별 통제 fixture의
   시작·진행·중단·결과·재접속을 확인한다. 지원하지 않는 로봇은 어댑터 안내로 남기고 OMX 화면
   응답을 범용 로봇 지원의 근거로 쓰지 않는다. AI에서는 운영 추론의 승인 revision·서비스 상태가
   전후 같고 lab 출력이 운영 모델 경로에 반영되지 않았는지도 확인한다.

실패 시 운영 이미지를 바꾸지 않거나 검증된 이전 후보로 되돌린다. 신뢰되지 않는 이미지나
미설정 인증을 통과시키기 위해 기존 보호 경계를 완화하지 않는다.
Site updater가 복구하는 site env/이전 후보 외에도, 외부 Learning JSON과 원격 서비스 구성은
각각 이전 버전·내용 hash를 보존하고 자체 건강 확인 실패 시 되돌린다. 운영 파일/계정 비밀은
코드·이미지·검증 출력에 포함하지 않는다.
복구는 신규 학습 접수를 막고 실행 중 작업과 산출물을 보존한 뒤, 원래 trusted controller·유닛·
코드 링크·private 설정을 함께 대조한다. 기존 운영 추론은 변경 대상으로 포함하지 않는다.
원복 후 이전 Fleet 진입·프로젝트 접근과 기존 검수 DB/라벨·운영 추론 상태를 다시 확인한다.
