import {createRequest} from './request.js';

// Fleet response semantics only. Documents own credentials, locks and polling.
export function createFleetClient(options = {}) {
  const request = createRequest(options);
  return async function call(path, init = {}) {
    let response;
    try { response = await request(path, init); }
    catch (error) {
      if (error?.name !== 'AbortError' && /Failed to fetch|NetworkError|ERR_/.test(error?.message || '')) {
        try { error.message = '관제 연결을 확인하지 못했습니다. 네트워크를 확인한 뒤 현재 상태를 다시 조회하세요.'; }
        catch { /* Immutable exceptions retain their original identity and message. */ }
      }
      throw error;
    }
    const {status, ok, body} = response;
    const isDetailObj = Boolean(body?.detail && typeof body.detail === 'object' && !Array.isArray(body.detail));
    const detail = isDetailObj ? body.detail : {};
    const topBody = (body && typeof body === 'object' && !('detail' in body)) ? body : {};
    const code = detail.code ?? (typeof topBody.code === 'string' ? topBody.code : undefined);
    const detailValue = detail.detail ?? (body?.detail !== undefined ? body.detail : undefined);
    const listSummary = Array.isArray(body?.detail) && body.detail.length
      ? body.detail.slice(0, 2).map((item) => {
          if (typeof item === 'string') return item;
          const loc = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
          return [loc, item?.msg || item?.type].filter(Boolean).join(': ');
        }).filter(Boolean).join('; ')
      : '';
    const rawDetailText = status < 500 && typeof body?.detail === 'string' && body.detail.trim() ? body.detail.trim() : '';
    if (status === 401) {
      const error = new Error('관제 인증이 필요합니다 — 로그인하거나 고급 접속을 확인하세요');
      error.status = status;
      error.code = code;
      error.detail = detailValue;
      error.path = String(path || '').split('?')[0];
      throw error;
    }
    if (!ok) {
      const error = new Error(detail.message || detail.code || topBody.message || topBody.code || listSummary || rawDetailText || (status >= 500
        ? '관제 서버 응답을 확인하지 못했습니다. 연결을 확인한 뒤 현재 상태를 다시 조회하세요.' : `HTTP ${status}`));
      error.status = status;
      error.code = code;
      error.detail = detailValue;
      error.path = String(path || '').split('?')[0];
      throw error;
    }
    return body;
  };
}
