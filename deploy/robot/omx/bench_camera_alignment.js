(() => {
  const panel = document.getElementById('camera-preparation');
  const status = document.getElementById('camera-preparation-status');
  const alignment = document.getElementById('camera-alignment-status');
  const reference = document.getElementById('side-reference');
  const current = document.getElementById('side-current');
  const save = document.getElementById('save-side-reference');
  const message = document.getElementById('side-reference-message');
  const labels = {
    top: '상단', side: '측면', arm_a_wrist: 'A 손목', arm_b_wrist: 'B 손목',
    matched: '등록 일치', unregistered: '장치 미등록', device_missing: '등록 장치 없음',
    binding_mismatch: '장치·영상 연결 불일치', registry_unavailable: '등록 확인 불가',
    ok: '조명 정상', missing: '조명 확인 불가', stale: '조명 확인 불가',
    lighting_mismatch: '조명 변화', no_baseline: '조명 기준 없음', unusable_lighting: '조명 이상',
  };
  const guidance = {
    no_reference: '측면 구도 기준이 없습니다. 작업대가 보이는지 확인하고 기준을 저장하세요.',
    manual_comparison: '자동 판정 불가 · 고정 마커 설정 없음. 기준과 현재 영상을 비교하세요.',
    markers_missing: '자동 판정 불가 · 기준 또는 현재 영상에서 고정 마커가 보이지 않습니다.',
    settings_invalid: '자동 판정 불가 · 고정 마커 설정을 확인하세요.',
    detector_unavailable: '자동 판정 불가 · 마커 검출기를 확인하세요.',
    reference_invalid: '측면 기준 파일 또는 영상 크기를 확인하세요.',
    side_unavailable: '현재 측면 프레임을 받을 수 없습니다.',
    aligned: '고정 마커가 구도 기준 범위 안에 있습니다.',
    moved: '현재 영상의 노란 점이 파란 목표점에 가까워지도록 카메라 구도를 맞추세요.',
  };
  let checking = false, saving = false, digest;
  const visible = () => panel.open && !panel.closest('[hidden]') && !benchSessionActive();

  function showPoints(image, pairs) {
    for (const point of image.parentNode.querySelectorAll('.side-alignment-point')) point.remove();
    for (const [points, kind] of pairs) {
      for (const [x, y] of points ?? []) {
        const point = document.createElement('span');
        point.className = `side-alignment-point ${kind}`;
        point.style.left = `${x * 100}%`;
        point.style.top = `${y * 100}%`;
        image.parentNode.append(point);
      }
    }
  }

  async function check() {
    if (!visible() || checking) return;
    checking = true;
    const selected = f.arm.value;
    const arm = selected === 'arm_a' || selected === 'arm_b' ? selected : 'arm_ab';
    try {
      const data = await api(`/api/camera_preparation?arm=${arm}`);
      status.replaceChildren(...Object.entries(data.cameras).map(([role, row]) => {
        const item = document.createElement('li');
        item.textContent = `${labels[role]} · ${labels[row.binding]} · ${row.ok ? '새 프레임 확인' : `프레임 문제 (${row.error})`} · ${labels[row.lighting]}`;
        return item;
      }));
      const side = data.side_alignment;
      digest = data.cameras.side.ok && data.cameras.side.binding === 'matched' ? side.current_sha256 : undefined;
      alignment.textContent = guidance[side.status] + (side.max_px === undefined ? '' : ` 최대 차이 ${side.max_px}px`);
      reference.hidden = !side.has_reference;
      if (side.has_reference && !reference.getAttribute('src')) reference.src = '/api/camera_alignment/reference.jpg';
      if (!side.has_reference) reference.removeAttribute('src');
      current.hidden = !side.current_jpeg;
      if (side.current_jpeg) current.src = `data:image/jpeg;base64,${side.current_jpeg}`;
      showPoints(reference, [[side.points?.reference, 'target']]);
      showPoints(current, [[side.points?.reference, 'target'], [side.points?.current, 'observed']]);
    } catch {
      digest = undefined;
      current.hidden = true;
      alignment.textContent = '카메라 준비 상태를 읽을 수 없습니다.';
      status.replaceChildren();
      showPoints(reference, []);
      showPoints(current, []);
    } finally {
      checking = false;
      save.disabled = saving || !digest;
    }
  }

  save.onclick = async () => {
    if (!visible() || saving || !digest) return;
    saving = save.disabled = true;
    try {
      await api('/api/camera_alignment', {confirmed: true, sha256: digest});
      reference.src = `/api/camera_alignment/reference.jpg?saved=${Date.now()}`;
      message.textContent = '측면 구도 기준을 저장했습니다.';
      await check();
    } catch (err) {
      message.textContent = err.message;
    } finally {
      saving = false;
      save.disabled = !digest;
    }
  };
  panel.ontoggle = check;
  setInterval(check, 1000);
})();
