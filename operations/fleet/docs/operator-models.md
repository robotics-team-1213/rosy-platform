# 관제 AI 다국어 모델 후보와 평가

2026-10-20 공식 모델 카드와 저장소를 확인했다. 아래는 운영 승격 전 후보이며 ROSY에서 한국어·영어 정확도나 지연을 실측한 결과가 아니다. 현재 승인 모델 `qwen3-vl:8b-instruct`의 digest는 유지한다. 코드/가중치 공개와 라이선스는 학습 데이터 전체 공개를 뜻하지 않는다.

| 역할 | 후보·라이선스 | 선택 이유와 확인할 점 |
|---|---|---|
| LLM 기준선 | 기존 Qwen3-VL 8B 고정 profile | 기존 broker·schema 출력 경로를 그대로 평가한다. 새 다국어 suite와 source/profile 결속이 필요하다. |
| LLM 비교 | [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), Apache-2.0 | 공식 카드의 100개 이상 언어 지원. 비교적 작은 텍스트 모델 후보이며 로봇명·부정·인용·좌표·엄격 JSON 성공률을 두 언어에서 측정한다. |
| LLM 비교 | [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), Apache-2.0 | 공식 카드의 201개 언어/방언 지원. 모델/런타임 세대가 달라 기존 digest를 문자열만 바꿔 재사용하지 않는다. 한국어/영어의 현장 품질은 별도 평가한다. |
| STT 비교 우선 | [Qwen3-ASR-1.7B/0.6B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), Apache-2.0 | 공식 지원표에 Korean·English가 명시되어 있고 오프라인/스트리밍 추론을 지원한다. 0.6B와 1.7B를 같은 발화로 비교한다. |
| STT 기준선 | [Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo), MIT; [faster-whisper](https://github.com/SYSTRAN/faster-whisper), MIT | 다국어 인식 기준선. faster-whisper는 모델과 별개인 CTranslate2 실행 엔진이다. 공식 속도 수치는 현장 성능으로 사용하지 않는다. |
| TTS 비교 | [Qwen3-TTS-12Hz-1.7B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice), Apache-2.0 | 공식 10개 언어에 한국어·영어가 포함된다. 고정 목소리로 숫자·로봇명 발음과 첫 음성 지연을 측정한다. |

우선순위는 기존 LLM을 유지해 두 언어의 의미/안전 평가를 끝내고, 브라우저 로컬 음성으로 시작하는 것이다. 목표 브라우저가 로컬 인식을 제공하지 않거나 현장 정확도가 부족하면 Qwen3-ASR와 Whisper를 AI PC에서 비교한다. 서버 STT/TTS는 아직 연결하지 않았다. 새 음성 패키지·가중치 자동 다운로드나 외부 음성 API는 이번 구현에 추가하지 않았다.

## 실행할 평가

1. 모델 PC에서 후보별 정확한 upstream revision, 변환/양자화 digest, 실행 엔진/버전, GPU 메모리와 동시 서비스 상태를 기록한다. 모델 이름과 라이선스만 확인한 상태는 운영 승인으로 세지 않는다.
2. LLM은 `python -m deploy.ai_pc.operator_acceptance --source-commit <전체-SHA> --output <비공개-경로>`로 고정된 한국어/영어 사례를 실행한다. 모든 사례 통과, STATUS의 실제 reference 일치, 부정·인용의 CONTROL 금지, 타인 대화·자격 정보·안전 우회 거부가 필수다. 출력 schema/source/profile/suite hash와 7일 유효 기간을 설치기가 검증한다. 후보 비교는 profile을 별도 구현·예약하고 평가해야 하며 현재 literal digest 검증을 풀지 않는다.
3. 음성은 언어별 최소 20개 동일 녹음으로 로봇명·목적지·숫자·부정·혼합 언어·소음·무음을 포함한다. 인식 원문, 수정한 문장, 핵심 로봇/목적지/부정 일치, CER/WER, p50/p95 지연·최대 메모리·무음 오인식·취소 후 자원 해제를 기록한다. 실제 녹음은 동의를 받고 비공개 증거에 보관한다.
4. 핵심 대상/부정 의미 오류나 자동 실행은 0이어야 한다. 최종 STT 문장은 항상 편집 가능한 입력란으로 들어가며 운영자가 전송한다. 다른 언어로 자동 번역한 뒤 실행하지 않는다. 지연 예산과 일반 인식 오차 허용치는 관제 PC 실측과 운영자 수용으로 확정한다.
5. 음성 엔진 변경은 텍스트·실행 권한을 변경하지 않는다. 실제 Task 결과는 기존 Fleet owner 관측만 표시한다. 한국어·영어 외 언어는 엔진의 공식 지원 목록과 별도 수용 사례를 추가한 뒤 locale 계약에 등록한다.
