// Draft editing only. The canonical compiler owns validation and device acceptance is separate.
export function renderStructuredDocument(kind, document, root, change) {
  root.replaceChildren();
  const get = path => path.reduce((value, key) => value?.[key], document);
  function group(title, collapsed = false) {
    const element = window.document.createElement(collapsed ? 'details' : 'fieldset');
    element.className = 'document-group';
    const heading = window.document.createElement(collapsed ? 'summary' : 'legend');
    heading.textContent = title; element.append(heading); root.append(element); return element;
  }
  function field(container, path, title, type = 'number', choices = null) {
    const label = window.document.createElement('label'); label.textContent = title;
    const input = window.document.createElement(choices ? 'select' : 'input');
    input.className = 'ui-field'; input.dataset.path = path.join('.');
    if (choices) {
      const values = [...new Set([...choices, ...(get(path) === undefined ? [] : [get(path)])])];
      for (const value of values) {
        const option = window.document.createElement('option'); option.value = value;
        option.textContent = value; input.append(option);
      }
    } else { input.type = type; if (type === 'number') input.step = 'any'; }
    if (type === 'checkbox') input.checked = get(path) === true;
    else input.value = get(path) ?? '';
    input.setAttribute('aria-describedby', 'notice');
    input.addEventListener(type === 'checkbox' || choices ? 'change' : 'input', () => change(draft => {
      const parent = path.slice(0, -1).reduce((value, key) => value[key], draft);
      parent[path.at(-1)] = type === 'checkbox' ? input.checked :
        type === 'number' ? (input.value === '' ? null : Number(input.value)) : input.value;
    }));
    label.append(input); container.append(label); return input;
  }
  function button(container, title, mutate, id = null, dataset = null) {
    const control = window.document.createElement('ui-button');
    control.textContent = title; control.setAttribute('kind', 'quiet');
    control.dataset.documentEdit = kind;
    if (id) control.id = id;
    if (dataset) Object.assign(control.dataset, dataset);
    control.addEventListener('click', () => change(mutate, true)); container.append(control); return control;
  }
  if (kind === 'recipe') {
    const general = group('작업 설정');
    field(general, ['name'], '레시피 이름', 'text');
    field(general, ['mode'], '작업 방향', 'text', ['palletize', 'depalletize']);
    field(general, ['pick_station'], '공급 스테이션', 'text');
    for (const [index] of (document.pallets ?? []).entries()) {
      const pallet = group(`팔레트 ${index + 1}`);
      for (const [key, title, type] of [
        ['id', '팔레트 ID', 'text'], ['frame', '팔레트 프레임', 'text'],
        ['length', '길이 (m)'], ['width', '폭 (m)'],
        ['max_stack_height', '최대 적재 높이 (m)'], ['max_load_kg', '최대 적재 질량 (kg)']]) {
        field(pallet, ['pallets', index, key], title, type);
      }
      button(pallet, '이 팔레트 삭제', draft => draft.pallets.splice(index, 1));
    }
    button(root, '팔레트 추가', draft => (draft.pallets ??= []).push({
      id: '', frame: '', length: null, width: null, max_stack_height: null, max_load_kg: null,
    }), 'recipe-pallet-add');
    for (const [index] of (document.layers ?? []).entries()) {
      const layer = group(`${index + 1}층`);
      field(layer, ['layers', index, 'pattern'], '배치 패턴', 'text', ['grid', 'split']);
      field(layer, ['layers', index, 'mirrored'], '대칭 배치', 'checkbox');
      field(layer, ['layers', index, 'slip_sheet_below'], '이 층 아래 슬립시트', 'checkbox');
      button(layer, '이 층 삭제', draft => draft.layers.splice(index, 1), null, {removeLayer: String(index)});
    }
    button(root, '층 추가', draft => (draft.layers ??= []).push({pattern: 'grid'}), 'recipe-layer-add');
    const sheet = group('슬립시트 설정');
    const enabled = window.document.createElement('input'); enabled.type = 'checkbox';
    enabled.id = 'recipe-sheet-enabled'; enabled.checked = Object.hasOwn(document, 'slip_sheet');
    const label = window.document.createElement('label'); label.textContent = '슬립시트 설정 포함';
    enabled.addEventListener('change', () => change(draft => {
      if (enabled.checked) draft.slip_sheet = draft.schema === 'rosy_cell.recipe/2' ?
        {handling: 'operator', thickness: null} : {thickness: null, station: ''};
      else delete draft.slip_sheet;
    }, true));
    label.append(enabled); sheet.append(label);
    if (enabled.checked) {
      const handling = window.document.createElement('select');
      handling.className = 'ui-field'; handling.id = 'recipe-sheet-handling';
      for (const [value, title] of [['robot', '로봇 집기'], ['operator', '작업자가 넣고 확인 후 다음 층']]) {
        const option = window.document.createElement('option'); option.value = value;
        option.textContent = title; handling.append(option);
      }
      handling.value = document.slip_sheet?.handling === 'operator' ? 'operator' : 'robot';
      const handlingLabel = window.document.createElement('label'); handlingLabel.textContent = '슬립시트 취급';
      handlingLabel.append(handling); sheet.append(handlingLabel);
      handling.addEventListener('change', () => change(draft => {
        const thickness = draft.slip_sheet.thickness;
        draft.schema = handling.value === 'operator' ? 'rosy_cell.recipe/2' : 'rosy_cell.recipe/1';
        draft.slip_sheet = handling.value === 'operator' ? {handling: 'operator', thickness} :
          {thickness, station: ''};
      }, true));
      field(sheet, ['slip_sheet', 'thickness'], '두께 (m)');
      if (handling.value === 'robot') field(sheet, ['slip_sheet', 'station'], '슬립시트 공급 스테이션', 'text');
      else {
        const note = window.document.createElement('p');
        note.textContent = '간지 지점에서 삽입 확인을 기다립니다. 작업자 접근 허가가 확인되기 전에는 다음 층을 진행할 수 없습니다.';
        sheet.append(note);
      }
    }
  } else {
    const rules = group('프레임 판정 기준');
    for (const [key, title] of [
      ['min_span_m', '최소 점 간격 (m)'], ['min_angle_deg', '최소 점 각도 (deg)'],
      ['max_tilt_deg', '최대 프레임 기울기 (deg)']]) {
      if (document.frame_rules) field(rules, ['frame_rules', key], title);
    }
    for (const name of Object.keys(document.frames ?? {})) {
      const frame = group(`프레임 ${name} · 티칭값 입력`, true);
      for (const [point, title] of [['origin', '원점'], ['x_point', 'X축 점'], ['plane_point', '평면 점']]) {
        for (const [index, axis] of ['x', 'y', 'z'].entries()) {
          field(frame, ['frames', name, point, index], `${title} ${axis} (m)`);
        }
      }
    }
    for (const name of Object.keys(document.stations ?? {})) {
      const station = group(`스테이션 ${name}`, true);
      field(station, ['stations', name, 'frame'], '기준 프레임', 'text', Object.keys(document.frames ?? {}));
      for (const axis of ['x', 'y', 'z', 'yaw']) {
        field(station, ['stations', name, axis], `${axis} (${axis === 'yaw' ? 'rad' : 'm'})`);
      }
    }
  }
}
