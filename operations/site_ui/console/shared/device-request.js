import {createRequest} from './request.js';

// Device panels retain their own error text and complete Fleet detail object.
export function createDeviceRequest({scope, headers}) {
  const request = createRequest({credential: () =>
    new Headers(headers()).get('Authorization')?.replace(/^Bearer /, '') || ''});
  return async (path, {method = 'GET', body} = {}) => {
    const life = scope.capture();
    life.check();
    const init = {method, headers: {...headers()}, signal: life.signal};
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const response = await request(path, init);
    life.check();
    return response;
  };
}
