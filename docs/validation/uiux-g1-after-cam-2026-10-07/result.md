# ROSY UI/UX G1 current-tree check — 2026-10-07

Local `main` candidate: `8f16858b73b57e0f013103c1e33691858823b31f`.

Ran D-153's available machine checks after the Cam pairing change:

```text
python -m pytest shared/web/test/test_palette_gates.py shared/web/test/test_ui_token_contracts.py operations/fleet/test/test_grammar_separation.py middleware/core/gateway/test/test_evidence.py shared/web/test/test_responsive_tiers.py -q -rfE -p no:cacheprovider
python test/known_failures.py <run log>
```

Result: **90 passed, 1 Starlette/anyio deprecation warning; 0 NEW known failures**. Raw log: `X:/DevTemp/projects/rosy-platform/2026-10-07--g1-after-cam/g1.txt`, SHA-256 `b25d9927a69e84ff45808ab0c8a0f0bb14e124eb14c92ae15fe172e414b48686`.

This proves the named local G1 checks on this SHA only. D-153 G2 declared states and widths, G3 operator review, current site/device readback, and CI for local commits remain **HOLD**.
