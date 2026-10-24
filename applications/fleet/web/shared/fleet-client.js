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
    if (status === 401) {
      const error = new Error('관제 인증이 필요합니다 — 로그인하거나 고급 접속을 확인하세요');
      error.status = status;
      throw error;
    }
    if (!ok) {
      const detail = body?.detail || {};
      const error = new Error(detail.message || detail.code || (status >= 500
        ? '관제 서버 응답을 확인하지 못했습니다. 연결을 확인한 뒤 현재 상태를 다시 조회하세요.' : `HTTP ${status}`));
      error.status = status;
      error.code = detail.code;
      error.detail = detail.detail;
      throw error;
    }
    return body;
  };
}
