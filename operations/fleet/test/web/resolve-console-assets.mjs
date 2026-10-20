// D-518. 브라우저 지정자 /console/assets/<이름>을 web/shared, web/cell, web/work, web/ 파일로 푼다.
// node --test 가 문서 모듈의 그 import를 읽게 하는 훅이다. 제품 서버는 allowlist로 같은 이름을 서빙한다.

import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WEB = new URL("../../../../applications/fleet/web/", import.meta.url);
const PREFIX = "/console/assets/";
const FOLDERS = ["shared/", "cell/", "work/", "devices/", "sitemap/", "installation/", "map/", ""];

function asset(name) {
  if (!/^[\w.-]+\.(?:js|css)$/.test(name)) return null;
  for (const url of FOLDERS.map((folder) => new URL(`${folder}${name}`, WEB))) {
    if (existsSync(fileURLToPath(url))) return { url: url.href, shortCircuit: true };
  }
  return null;
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith(PREFIX)) {
    const found = asset(specifier.slice(PREFIX.length));
    if (found) return found;
  }
  // D-798: 브라우저는 콘솔 문서의 "./x.js"를 공개 URL /console/assets/에 맞춰 푼다. 하위 폴더로 옮긴
  // 파일끼리 디스크 경로가 달라도 같은 이름으로 찾게 한다.
  if (specifier.startsWith("./") && context.parentURL?.startsWith(WEB.href)) {
    const local = new URL(specifier, context.parentURL);
    if (!existsSync(fileURLToPath(local))) {
      const found = asset(specifier.slice(2));
      if (found) return found;
    }
  }
  return nextResolve(specifier, context);
}
