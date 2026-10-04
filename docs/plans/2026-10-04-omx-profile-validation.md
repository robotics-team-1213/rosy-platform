# OMX Episode 본문 검증과 Q6 해소

공통 DatasetManifest의 파일 해시 검증은 시연의 시간·관절·이미지 형식을 보증하지 않는다.
`contracts/learning`에 ROS와 학습 라이브러리 없이 실행되는 OMX profile 검증을 둔다.
기존 완성 시연의 provenance, radian 목표, 50 ms skew, fps 간격, 완료 상태,
원본 파일 SHA와 PNG 크기·RGB·CRC 검사를 유지한다. PNG 압축 스트림과 행 길이도 검사한다.
단위와 제한은 profile v1에 고정하며 runtime actuator 허가로 해석하지 않는다.

1. 잘못된 시계·관절 목표·완료 상태·PNG 및 공통 manifest 위조의 거부 테스트를 먼저 작성한다.
2. 기존 순수 검증을 공통 profile로 옮기고 stdlib PNG 검증을 구현한다.
3. curation의 middleware import를 제거하고 DatasetStore에서 OMX 본문과 wrapper 연결을 검사한다.
4. 기존 실제 6개 SIM Episode snapshot을 새 검증기로 다시 읽고, 영향 테스트와 독립 리뷰를 수행한다.

device recorder와 runtime wheel 설치는 이 단계에서 이전하지 않는다. recorder의 기존 Pillow
검증은 유지하며 동일 정상·오류 입력에 대한 offline profile과의 일치를 검사한다.
Pinky/Pilot 본문 profile은 검증기가 없으므로 DatasetStore에서 등록을 거부한다.
profile 이름 변경으로 OMX 검사를 우회하지 못하며 각각 별도의 후속 단계가 필요하다.
D-427 Q6의 learning→middleware edge만 제거하며 다른 wave 경로와 main은 수정하지 않는다.
