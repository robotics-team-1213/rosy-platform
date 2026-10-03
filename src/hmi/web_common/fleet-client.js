import {createRequest} from './request.js';

// Fleet response semantics only. Documents own credentials, locks and polling.
export function createFleetClient(options = {}) {
  const request = createRequest(options);
  return async function call(path, init = {}) {
    const {status, ok, body} = await request(path, init);
    if (status === 401) {
      const error = new Error('관제 토큰이 필요합니다 — 상단에 입력하고 접속을 누르세요');
      error.status = status;
      throw error;
    }
    if (!ok) {
      const detail = body?.detail || {};
      const error = new Error(detail.message || detail.code || `HTTP ${status}`);
      error.status = status;
      error.code = detail.code;
      throw error;
    }
    return body;
  };
}
