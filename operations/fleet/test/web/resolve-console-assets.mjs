// D-518. 브라우저 지정자 /console/assets/<이름>을 web/shared, web/cell, web/ 파일로 푼다.
// node --test 가 문서 모듈의 그 import를 읽게 하는 훅이다. 제품 서버는 allowlist로 같은 이름을 서빙한다.

import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WEB = new URL("../../fleet/server/web/", import.meta.url);
const PREFIX = "/console/assets/";

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith(PREFIX)) {
    const name = specifier.slice(PREFIX.length);
    if (/^[\w.-]+\.(?:js|css)$/.test(name)) {
      for (const url of [new URL(`shared/${name}`, WEB), new URL(`cell/${name}`, WEB), new URL(name, WEB)]) {
        if (existsSync(fileURLToPath(url))) {
          return { url: url.href, shortCircuit: true };
        }
      }
    }
  }
  return nextResolve(specifier, context);
}
