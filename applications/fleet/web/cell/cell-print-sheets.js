// Calibration print sheets (one arm slot's markers, ChArUco, checkerboard) as real-size PDF from the Fleet server.
// Each arm slot owns its own marker ids (D-933), so the arm sheet asks for the slot chosen in #print-arm.
// The client parses JSON, so the PDF comes base64-encoded and is saved here as a file.

export const PRINT_SHEETS = [
  {id: 'print-arm-markers', kind: 'arm-markers', query: '', label: '팔 마커', arm: true},
  {id: 'print-charuco', kind: 'charuco', query: '', label: 'ChArUco 보정판'},
  {id: 'print-checkerboard', kind: 'checkerboard', query: 'cols=8&rows=6&square_mm=15', label: '체커보드'},
];

export function sheetPath(sheet, arm = '1') {
  const query = sheet.arm ? `arm=${encodeURIComponent(arm)}` : sheet.query;
  return `/api/fleet/cell-app/print-sheets/${encodeURIComponent(sheet.kind)}?${query}`;
}

export function pdfBytes(base64) {
  const text = atob(base64);
  const bytes = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) bytes[i] = text.charCodeAt(i);
  return bytes;
}

export function bindPrintSheets({request, $}) {
  const status = $('print-status');
  for (const sheet of PRINT_SHEETS) {
    $(sheet.id).addEventListener('click', async () => {
      status.textContent = `${sheet.label} PDF를 만드는 중입니다.`;
      try {
        const body = await request(sheetPath(sheet, $('print-arm').value));
        const url = URL.createObjectURL(new Blob([pdfBytes(body.pdf_base64)], {type: body.media_type}));
        const link = document.createElement('a');
        link.href = url; link.download = body.filename;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        status.textContent = `${body.filename} 저장 · 100%(실제 크기)로 인쇄하고 50 mm 막대를 자로 확인하세요.`;
      } catch (error) {
        status.textContent = `${sheet.label} PDF를 만들지 못했습니다: ${error.message}`;
      }
    });
  }
}
