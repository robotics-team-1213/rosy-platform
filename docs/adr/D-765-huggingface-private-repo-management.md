## D-765 Hugging Face 연결로 비공개 데이터셋과 모델 저장소를 관리

**Status:** Accepted (2026-10-14)

### Context

D-755는 Hugging Face 로그인과 읽기 토큰을 고정 버전 가져오기에 쓴다. `learning.publish`는
계정 계약에 있으나 저장소 관리 경로가 없다. 같은 연결로 데이터셋과 모델 저장소를 관리할
수 있어야 한다. 이 결정은 검수 앱의 비공개 저장소 목록·생성·삭제이며, 파일 업로드·Spaces
실행·공개 전환·학습 수용의 증거가 아니다.

### Decision

`learning.publish`가 있는 사용자만 저장된 연결로 비공개 dataset·model 저장소를 조회·생성·삭제한다.
`learning.import`와 `learning.manage`는 이 권한을 대신하지 않는다. 연결을 저장하는 일은 계속
`learning.import`가 필요하므로 publish만으로는 토큰을 보관하지 않는다.

PAT는 whoami의 role로 저장소 범위를 기록한다. read는 `read-repos`이고, 제한 자료 읽기는
그 응답이 참일 때만 더한다. write는 생성·삭제를 포함한 알려진 범위다. fine-grained는 응답
목록에 있는 알려진 범위만 기록한다. 근거가 없으면 관리 범위는 없다. OAuth 로그인은
`openid profile`만 요청한다. 자료 연결은 `read-repos`와 `gated-repos`만 요청하고, 그 교집합만
저장한다. 저장소 관리 연결은 `read-repos`, `write-repos`, `manage-repos`를 요청하고, 쓰기와
저장소 관리가 모두 있을 때만 연결한다. 요청하지 않은 범위는 저장하지 않는다.

개인 연결은 그 Hugging Face 사용자 이름의 저장소만 만든다. 프로젝트 연결은 허용 목록에
있는 dataset·model만 다룬다. 조직 소속은 권한이나 허용이 아니다. 생성 본문은
`visibility: private`이며, 만든 뒤 조회 결과가 private가 아니면 실패한다. 그 경우 공개
상태를 바꾸거나 자동으로 지우지 않는다. 이미 있는 저장소(409)는 성공으로 보지 않는다.
삭제는 저장소 이름을 다시 입력하고, 조회 결과가 private일 때만 한다. 공개 저장소는 지우지 않는다.

토큰은 서버에 암호화되어 있고 브라우저, URL, 감사 기록에 반환하지 않는다. `HF_TOKEN`이나
CLI 로그인으로 계정을 바꾸지 않는다. 파일 업로드, Spaces, 컬렉션, 과금, 버킷, 추론은
이 경로에 없다. CORE `/api/v1`은 바꾸지 않는다.

### Consequences

읽기 연결과 기존 가져오기는 유지된다. 외부 게시는 별도 권한이며 자동 승인하지 않는다.
실제 Hugging Face 계정 수용과 파일 업로드는 후속이다.

### Validation

범위 기록, 개인·프로젝트 경계, 비공개 확인, 삭제 확인, 권한 거부를 주입한 전송으로 시험한다.
원격 pytest 결과를 `known_failures`와 비교한다. 호스트 시험은 장치·현장 수용을 대신하지 않는다.
