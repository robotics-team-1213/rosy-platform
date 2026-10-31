// Calibration print sheets (gripper markers, checkerboard) as real-size PDF from the Fleet server.
// The client parses JSON, so the PDF comes base64-encoded and is saved here as a file.

export const PRINT_SHEETS = [
  {id: 'print-markers', kind: 'gripper-markers', query: 'ids=0,1&sizes_mm=20,25', label: '그리퍼 마커'},
  {id: 'print-checkerboard', kind: 'checkerboard', query: 'cols=8&rows=6&square_mm=15', label: '체커보드'},
  {id: 'print-charuco', kind: 'charuco', query: '', label: 'ChArUco 보정판'},
  {id: 'print-surface-markers', kind: 'surface-markers', query: 'ids=35,36,37,38,39,40,41,42,43,44,45,46,47,48', label: '면 마커'},
];

export function sheetPath(sheet) {
  return `/api/fleet/cell-app/print-sheets/${encodeURIComponent(sheet.kind)}?${sheet.query}`;
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
        const body = await request(sheetPath(sheet));
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
