## 2026-11-26 · uncommitted · Pinky 표정 변화: 눈썹·볼터치·턴 신호 시선

- 변경: character.py가 눈썹, 보조 반짝임, 볼터치(BLUSH, 32x24 임계값 아래), scan/lost/worry/thinking 미세 움직임을 그린다. native tick은 표정 의도가 없을 때 좌/우 방향 신호 쪽으로 시선을 돌린다(resting 조건 유지). D-504 등의 깜빡임 없음을 지킨다. GIF 16개는 make_faces.py 결과와 같고 20프레임, 100ms, 320x240이다. LCD 문구 없음(영어 유지).
- 증거: 원격 집중 시험(face test 디렉터리, test_face_expression, test_rosy_face*, native systemd 계약) exit 0; 독립 검토에서 깜빡임을 지적받아 제거. 호스트 렌더는 실물 LCD 수용이 아니다.
- gate 변화: 없음
- 결정: 없음
- 교훈: 해당 없음 - 평범한 표현 변경
