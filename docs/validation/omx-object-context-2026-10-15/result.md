# OMX 물체 판독·제한 환경 문맥 실험

실행일: 2026-10-15. 기준 commit `a51b73974ab5eb58935fc6edd25f5de580f66b68`.
브랜치 `docs/omx-object-perception-experiments`. **동결 이미지 오프라인 실험**이며 장치 조작·FIELD 수용이 아니다.
전체 20회: Model PC 10회, AI PC 10회. 실제 명령 전송 0회.

## 입력과 출처

현장 top/front에서 각각 전진하는 프레임 3개 이상을 확인한 후 640×480 JPEG 각 1장을 고정했다.
수신 시각 기준 age 약 0.113/0.014초는 캡처 당시 값이며 실험 시점의 영상 신선도나 노출시각이 아니다.
원본은 비공개 X: 세션 `2026-10-15--042252--inference-integration--f27cbc`의
`scratch/discussion-20261015125112/{top,front}.jpg`와 같은 폴더의 `frames.json`에 보관한다.
이미지/base64/실제 호스트는 커밋하지 않는다.

| 입력 | SHA256 |
|---|---|
| top.jpg SHA256 | `1e3f8dcd40dbb0d986aeb56770c4006eab75710a10ebb69493be976d2bae1848` |
| front.jpg SHA256 | `60f762f3490346e5a1547b82b3f7c82d8c8ecb9d1a701f2cf1c14584925e15de` |
| 두 PC 모델 digest | `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319` |

두 PC 모두 `qwen3-vl:8b-instruct`, temperature 0, seed 42. 같은 가중치이므로 상호 동의는 독립 검증이 아니다.
카메라 발행기는 앞선 수정 snapshot `dbe5db55b`이며 Fleet 운영 컨테이너의 배포 SHA와 혼동하지 않는다.
실험은 각 PC loopback Ollama `/api/chat`을 사용했다. 상시 카메라→AI→Fleet 파이프라인을 설치한 시험은 아니다.

top 직접 검토의 임시 참조는 갈색 원통형 7영역(전체 4·경계 3), 흰 원형 1영역,
위쪽 경계의 딸기 모양 1영역이다. **assistant 수작업 참조이며 독립 사람 정답이 아니다.**
front는 근접하고 흐린 하드웨어와 바닥 위주로 대상 물체를 식별하지 못했다. 기기 고장을 입증하지 않는다.

## 실행과 결과

| 단계 | 호출 | 결과 | 다음 개선 |
|---|---:|---|---|
| A 자유 서술 | 4 | 두 PC top에서 같은 개수, 흰 영역을 구슬로 단정. front 설명은 관측 부족과 작동 불가를 혼동 | 외형·역할·운용 상태 분리 |
| B pixel JSON 요청 | 4 | top 두 응답은 640×480 요청에 상대좌표 같은 값 반환, 범위 검사 거절. front 빈 목록 통과 | 제공자 좌표 규약 명시 |
| B2 normalized 명시 | 2 | 두 응답 모두 `[945,]` 때문에 JSON 문법 오류 | 누락 좌표를 추측 복구하지 않음 |
| C 문맥 v2 추가 | 4 | top 두 응답 9영역, front 빈 목록. 선택된 형식·좌표 검사 통과 | 경계 가림은 여전히 오판 |
| B3 constrained JSON schema | 2 | 두 응답 9영역, 형식·좌표 검사 통과 | 스키마는 의미 정확도를 보증하지 않음 |
| D 실제 상대 결과 검토 | 2 | 서로의 C 결과와 같은 이미지를 보고 corrections 빈 목록. 용기·단계 미확인, 완료 주장 없음 | 공유 오류를 독립 검사로 적발 |
| E 사용자 확인 문맥 v3 | 2 | 둘 다 흰 원형 물체=용기, 근거=user_statement 반환 | 사용자 역할과 관측 상태를 구분 |

B2는 응답 끝이 정상 종료된 형태여서 토큰 절단이 원인이라고 입증하지 못했다.
D는 요청한 `agreed_facts`를 두 PC 모두 누락했다. 당시 부분 parser의 parse_error=null을
전체 요청 충족으로 세지 않는다. 재분석은 `missing_requested_fields`로 분류한다.
E는 별도 task 요약 스키마가 null/false를 강제한다. 이는 문맥 역할 readback 시험이며
관측만으로 미완료를 자율 판정하는 능력이나 C와의 정확도 비교가 아니다.

C/B3 top 각 9영역은 임시 참조와 label+IoU≥0.5에서 9개씩 대응했다.
각 응답의 visibility는 모두 fully_visible여서 참조와 5/9만 일치했다.
특히 딸기와 오른쪽 원통 3개의 경계 가림을 놓쳤다. 이 값은 진단용이며 정확도·재현율 합격선이 아니다.
D의 두 PC 교환은 이 오류를 고치지 못했다. 장비 정체도 흰 fixture를 arm base/camera mount로
추측하는 등 검증되지 않았다. 개수가 맞더라도 집기 가능이나 물체 역할이 확인된 것이 아니다.

추가 HSV 빨강 연결영역 시험은 top 7영역, front 0영역을 냈다.
top의 딸기 후보 `[298,0,357,63]` 외에도 로봇의 빨간 부품·문자가 섞였다.
색 필터 단독을 semantic detector로 채택하지 않는다. 이동하는 딸기를 놓치는 고정 ROI도 피한다.
값은 [red-proposals.json](evidence/red-proposals.json)에 남겼다.

## 사용자 문맥 이력

v2: 첫 목표는 딸기를 꺼내 잠시 놓고 다시 넣는 것. 용기·임시 구역·현재 단계 모두 미확인.
v3: 사용자가 **흰 원형 물체가 용기**라고 확인했다. v2 실행은 소급 수정하지 않았다.
v3에도 내용물·형상/깊이·재질·임시 구역·현재 단계는 미확인이다.
top의 해당 흰 영역 임시 box `[170,290,279,398]`은 영상 표식일 뿐 robot 좌표가 아니다.
사용자 확인으로 그릇의 안쪽 공간이나 딸기가 현재 들어 있는지까지 확정하지 않는다.

## 재현과 증거 범위

- [responses.json](evidence/responses.json): 20개 응답·모델/이미지 hash·소요시간·부분 parser 결과.
- [prompts-no-images.json](evidence/prompts-no-images.json), [v3 prompts](evidence/task-v3-prompts-no-images.json): 이미지 제거 요청. 원본 messages hash는 이미지 포함이므로 이 파일 hash와 다르다.
- [context v2](evidence/context.json), [context v3](evidence/context-v3.json), [임시 참조](evidence/provisional-reference.json), [decoder schema](evidence/decoder-schema.json).
- `evidence/object_probe*.py`, `object_review.py`, `task_v3.py`: 당시 실험 스크립트. 원본2장·메타데이터와 loopback Ollama가 있어야 원래 호출을 재현할 수 있다. 운영 서비스가 아니다.
- `python docs/validation/omx-object-context-2026-10-15/evidence/analyze.py`는 원격 접속 없이 공개 응답의 선택 검사·임시 참조 대응을 재계산한다. self-check 포함. 출력은 [analysis.json](evidence/analysis.json).

재분석: geometry 선택 검사 8, 자유 서술 4, 요청 필드 누락 2, 좌표 거절 2, JSON 오류 2,
제한된 task readback 2. 완전한 JSON Schema validator나 독립 시각 평가를 구현한 것은 아니다.
증거 분석은 표준 라이브러리로 실행했고 pytest는 원격 전용 규칙을 따른다.
모델 지연은 단일 호출 측정값이며 벤치마크/실시간 제어 성능으로 쓰지 않는다.

Qwen 공식 [2D grounding notebook](https://github.com/QwenLM/Qwen3-VL/blob/main/cookbooks/2d_grounding.ipynb)은
Qwen3의 기본 좌표가 0..1000 상대좌표임을 설명한다. 10/15 받은 notebook의
SHA256 `24a39b56467c16aea1062e40157c00800e8f53266714e8270ca3238064fd9898`을 기록했다.
[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)의 `format` schema를 B3/E에 사용했다.
좌표 grid 1000을 실제 입력 image width로 꾸미지 않는다. 실제 입력은 640×480이다.

다음 작업과 UI/IL/RL 반영은 [물체·문맥 개선 계획](../../plans/2026-10-15-omx-object-context.md)에 있다.
실제 꺼내기·복귀, 시간축 추적, 보정·깊이·충돌·관절 feedback·정지, 독립 사람 검수는 이번 실험에서 확인하지 않았다.
