## D-232 OMX 제품 설정은 products/omx 이고, 보드 핀맵과 AI 자리는 그대로다

**Status:** Accepted (2026-09-25).

잇는 결정: [D-231](D-231-layered-source-roots-keep-package-names.md) 결정 1의 "OMX 설정 → `products/omx`",
[D-196](D-196-devices-and-robots-domains.md)·[D-207](D-207-one-owner-per-product-and-device-kind.md)(제품은 설정, 장치는 계열),
[D-228](D-228-decision-lives-in-core-features.md)·D-209(판단과 학습의 자리).

**Context:**

1. D-231 이동 뒤에 팔 코드는 `src/devices/omx/omx_adapter`에 있고, 그 안의 `omx.disabled.yaml`만 제품 설정이다. Pinky 설정은 이미 `src/products/pinky_pro`다.
2. `omx-f`와 `omx-ai`는 팔 모델 이름이다. 판단 라이브러리나 GPU 워커가 아니다.
3. `sensor_adc`의 채널 지도, `lamp_control`의 GPIO 19, `led`의 보드 서비스는 Pinky 보드 핀맵이다. BNO055만 차체에 묶이지 않은 칩이라 `devices/common`에 있다.

**Decision:**

1. **OMX 제품 설정은 `src/products/omx`다.** 패키지 이름은 `omx`다. 내용는 `config/omx.disabled.yaml`과 그것을 설치하는 `package.xml`·`CMakeLists.txt`뿐이다. 어댑터 코드, launch, `adapter.manifest.yaml`은 `src/devices/omx/omx_adapter`에 남는다.
2. **모델 이름은 패키지가 아니다.** `omx-ai`와 `omx-f`는 그 YAML의 `model` 값으로만 고른다. 측정 전에는 `model`이 빈다. 모델마다 패키지를 만들지 않는다.
3. **AI 워커 폴더는 만들지 않는다.** 판단은 `src/runtime/core_features/core_features/decision`, 카메라·차선 증거는 `src/runtime/control`의 perception, 재생과 라벨은 `tools/perception`이다. 코드가 생기기 전에 `services/ai_worker/`를 만들지 않는다 (D-231 결정 4).
4. **보드 핀맵은 `devices/pinky_pro`에 남긴다.** `bringup`, `sensor_adc`, `lamp_control`, `led`를 `devices/common`으로 올리지 않는다. 공통으로 옮기는 조건은 같은 드라이버를 핀맵 없이 둘째 차체가 쓰는 것이다. `imu_bno055`는 이미 그 조건이라 `devices/common`이다.
5. **URDF는 `src/sim/description`에 남긴다.** 팔 모델이 비어 있는 동안 제품 조립으로 옮기지 않는다 (D-231).

**Consequences:**

- 이미지의 io 단계가 `src/products/omx`를 복사하고 `omx`를 빌드한다. 어댑터 share에는 그 YAML이 없다.
- `python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml` 은 `{}`를 낸다.
- 패키지 이름 `core`와 설치 경로 `install/lib/core/core`는 그대로다.

**Validation:** `python -m pytest src/products/omx/test src/devices/omx/omx_adapter/test test/architecture/test_target_layout.py test/architecture/test_module_structure.py test/test_robot_runtime.py -q`.
