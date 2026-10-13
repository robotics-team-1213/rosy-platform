# D-714 고정 프로파일 파일과 설치 제공자 구성 결속

**Status:** Accepted (2026-10-12, source contract)

root composition의 load_incident_profile_config는 설치 관리자가 별도 전달한 파일 SHA256과 최대 64 KiB JSON 명세를 검증한다. 내부 명세는 schema=rosy.incident.profiles/1, profile_sets만 허용하며 각 set은 기존 ModelProfile 전체 필드의 primary/reviewer 1~2개, 전체 set은 최대 8개다. 설치한 provider/config 객체의 전체 profile과 일치하는 set만 기존 D-713 profile_workers 구성으로 전달한다. 같은 set 중복·미설치 identity/revision/예산·변조·소유된 시계 재정의는 거절한다.

JSON 파일에는 실행 경로·주소·credential·명령어·호출 권한을 넣지 않는다. 제공자 객체를 파일에서 import/생성하거나 실행하지 않는다. 기존 admission/current_profiles/budget/enabled 및 보정 승인 포트는 보존하고 clock은 root가 명시한다. 최종 호출은 기존 제공자 admission·profile binding·안전/예산과 D-712 선택을 계속 거친다.

별도 SHA는 신뢰된 설치 구성의 값이어야 하며 파일 안의 자기 보고 hash가 아니다. 이 결속은 설치 명세 일치 증거이며 signed 운영 품질 수용이나 실제 호스트 설치 성공이 아니다. 실제 승인 근거·trust 설치·provider 결과·운영/현장 readback은 별도로 확인한다. public 문서에는 비공개 설정 값을 넣지 않는다.
