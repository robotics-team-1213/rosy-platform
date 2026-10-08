// D-518. `node --import` 이 파일을 먼저 읽어 콘솔 자산 지정자를 푼다.
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);
