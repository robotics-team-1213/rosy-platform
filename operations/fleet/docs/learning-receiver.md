# 학습 증거 내부 수신

현재 구현은 유한한 내부 증거 검증용이다. 전체 source를 base64 JSON bundle 하나와 SQLite BLOB 하나로 보존하므로 대용량 영상 수집의 메모리·저장 용량 수용은 검증하지 않았다. 운영 수신 서비스로 전환하려면 인증, 용량 제한, 저장 매체와 실제 전달 경로를 별도로 검증해야 한다.

`fleet.server.learning_receiver.LearningReceiver`는 기존 offline Fleet export와
Episode manifest·원본 receipt·source files를 SQLite에 함께 보존한다.
HTTP route와 서버 자동 실행은 추가하지 않는다. 실제 운영 전달·인증·Task 완료·
모델 추론·승격·학습 GT는 이 metadata 수신으로 증명되지 않는다.

Fleet와 `rosy-contracts-learning>=0.1.8`을 설치한 환경에서 다음을 실행한다.
소스 환경은 `operations/fleet`, `contracts/foundation`, `contracts/learning/src`를
`PYTHONPATH`에 둔다. Fleet image에는 공용 계약 source를 함께 넣지만 수신기는
기본 console factory에서 실행하지 않는다. Windows 산출물은 X에 둔다.

```text
python -m fleet.server.learning_receiver
  --database <receiver.sqlite3>
  --export <fleet-export.json>
  --episode <episode-root>/manifest.json
  --receipt <original-owner-receipt.json>
```

수신은 기존 OMX demonstration·OMX policy execution·Pinky recording profile
검증기를 사용한다. 지원하지 않는 Pilot은 거절한다. 전체 입력 bytes를 고정한 뒤
자기 snapshot에서 profile·input SHA·기존 export binding을 검증한다. task unknown과
null policy를 보존하고 matched와 unmatched 기록을 그대로 받는다. matched는
상관 키의 일치이며 live receipt 인증이나 과제 성공 수용이 아니다.

같은 export revision과 같은 전체 bytes는 하나의 행만 남는다. 같은 revision의
다른 raw bytes는 충돌이며 기존 행을 바꾸지 않는다. 한 FULL/WAL transaction에
전체 bundle을 저장한다. `get(revision)`은 coherent row snapshot에서 파일 해시와
profile·binding을 다시 검사한다. 원본 파일이 이후 사라져도 보존 snapshot은 유지한다.
SQLite commit 성공은 해당 저장 매체의 전원 손실 시험을 대신하지 않는다.

저장 SHA·source metadata·binding의 불일치는 거절한다. 모든 bytes·hash·metadata를
같이 다시 쓰는 공격자를 인증할 외부 anchor는 없다. 이 API는 grant/current authority·
학습 정답·승격 상태를 생성하거나 기존 Task/Action 원장을 변경하지 않는다.
