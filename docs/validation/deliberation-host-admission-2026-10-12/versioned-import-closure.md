# GLM v2 설치 의존성·import 검증

상위 계약은 D-681 및 [runtime 수용 계획](../../plans/2026-10-12-incident-runtime-admission.md)이다. 실제 모델·운영·비용·장치 수용은 HOLD다.

## 소스와 준비물

고정 소스 `cfcba82ddf5dee95b781d4cb9794f84605aa4f2e`의 tracked 파일 52개와 내부 manifest를 묶었다. source archive는 53 regular files, 227678 bytes, SHA-256 `b2a9365c5917e480f756ef94487d3627b7fa12157001c7ba1954fad8904e2f02`이다. source tree·tar·script·wheel을 고정한 manifest SHA는 `45b75fedd6b5e6d6b360f5e8af63884d1fbf0b873512f8939f0c59a7aac10b40`이다. 준비물은 `X:/DevTemp/glm-v2-bundle-7da923`이며 AI PC의 `/tmp/rosy-glm-v2-cfcba82ddf`에 업로드했다.

v2 gateway는 host의 pinned venv `sys.executable`과 Decision·Foundation source path를 사용한다. legacy v1 child는 기존 `/usr/bin/python3` 경로를 유지한다. snapshot은 root 소유로만 설치하며 경로 탈출·링크·기존 소스 불일치를 거절한다. offline wheel 5개는 hash 고정한 `requirements-deliberation-v2.txt`를 사용한다. 독립 검토에서 소스 blob·archive·manifest·wheel·스크립트 일치와 경로·권한 검사를 확인했다.

## 실제 임시 환경 검증

AI PC의 비특권 계정으로 별도 `import-check` source와 `import-check-venv`를 만들었다. manifest와 모든 wheel SHA 검사 후 empty environment의 offline `--no-index --no-deps --require-hashes` 설치·`pip check`·`deploy.ai_pc.deliberation_import_probe`를 실행했다. terminal exit 0, `No broken requirements found`, `PASS_V2_IMPORT_CODEC_ONLY`를 확인했다.

실제 installed versions는 pydantic 2.13.4, pydantic-core 2.46.4, annotated-types 0.8.0, typing-extensions 4.16.0, typing-inspection 0.4.4다. probe는 Linux x86_64·CPython 3.12 venv·고정 package versions·v2 codec 왕복 및 기본 admission false를 검사한다. 모델 호출·credential 읽기·호출 표식 변경은 없고 action/runtime/cost flags는 false다. 이 비특권 임시 환경 검증은 root readonly 설치나 service account 격리·실제 provider 수용을 증명하지 않는다.

## 관리자 설치 readback

업로드된 `glm-v2-prepare-admin.sh`는 root snapshot·copied venv·offline hashlocked install·전체 owner/mode/link 검사·import/codec·기존 offline host preflight까지만 수행한다. credential importer·온라인 요청·spent marker 초기화를 포함하지 않는다. 관리자 실행과 그 최종 로그는 아직 확인하지 못했다.

사용자의 OpenSSH 명령은 `ssh.exe -t <AI_PC> bash /tmp/rosy-glm-v2-cfcba82ddf/glm-v2-prepare-admin.sh`다. sudo 비밀번호가 필요하다. 출력의 `PASS_V2_IMPORT_CODEC_ONLY`, host preflight 상태, `PREPARE_EXIT=0`과 root source/venv readback을 각각 확인한다. 성공하더라도 actual provider·billing·calibration·Fleet activation·FIELD는 별도로 남는다.
