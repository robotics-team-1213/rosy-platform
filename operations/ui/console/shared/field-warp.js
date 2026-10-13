// 출력 픽셀마다 h(캔버스 px → 원본 px)로 원본을 표본한다(최근접). 원본 밖·지평선 뒤는 비운다.
// 편 결과를 돌려주어 같은 프레임·변환에서는 다시 계산하지 않는다.
// 공유 읽기다(D-518). 설치 제안 화면은 field-view.js가 가진다.

export function warpImage(ctx, image, h, width, height, scratch) {
  const iw = image.naturalWidth;
  const ih = image.naturalHeight;
  if (!iw || !ih) return null;
  scratch.width = iw;
  scratch.height = ih;
  const sctx = scratch.getContext("2d", { willReadFrequently: true });
  sctx.drawImage(image, 0, 0);
  const src = sctx.getImageData(0, 0, iw, ih).data;
  const out = ctx.createImageData(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const px = x + 0.5;
      const py = y + 0.5;
      const w = h[6] * px + h[7] * py + h[8];
      if (!(w > 0)) continue;
      const sx = Math.round((h[0] * px + h[1] * py + h[2]) / w);
      const sy = Math.round((h[3] * px + h[4] * py + h[5]) / w);
      if (sx < 0 || sy < 0 || sx >= iw || sy >= ih) continue;
      const s = (sy * iw + sx) * 4;
      const d = (y * width + x) * 4;
      out.data[d] = src[s]; out.data[d + 1] = src[s + 1]; out.data[d + 2] = src[s + 2]; out.data[d + 3] = 255;
    }
  }
  ctx.putImageData(out, 0, 0);
  return out;
}
