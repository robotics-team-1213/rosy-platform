// The arm's object catalogue with measured masses (D-934, D-935): read only, from the catalogue on the Fleet host.

export const CATALOG_PATH = '/api/fleet/cell-app/object-catalog';

export function catalogRows(body) {
  return (body?.objects || []).map(o => [
    o.kind ? `${o.id} (${o.kind})` : o.id,
    [o.length_mm, o.width_mm, o.top_height_mm].map(v => v ?? '—').join(' × '),
    o.mass_kg == null ? '미측정' : `${(o.mass_kg * 1000).toFixed(1)} g`,
    o.mass_measured ? `${o.mass_measured.at ?? '—'} · ${o.mass_measured.source ?? '—'}` : '—',
    String(o.carry || '').startsWith('blocked') ? '불가 · 잰 무게 없음' : '무게 있음 · 운반 때 상한 확인',
  ]);
}

export async function showObjectCatalog({request, $}) {
  const status = $('catalog-status');
  try {
    const rows = catalogRows(await request(CATALOG_PATH));
    $('catalog-rows').replaceChildren(...rows.map(cells => {
      const tr = document.createElement('tr');
      for (const value of cells) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      }
      return tr;
    }));
    $('catalog-table').hidden = !rows.length;
    status.textContent = rows.length ? `물체 ${rows.length}개` : '카탈로그에 물체가 없습니다.';
  } catch (error) {
    $('catalog-table').hidden = true;
    status.textContent = `물체 카탈로그를 읽지 못했습니다: ${error.message}`;
  }
}
