# D-153 G1 current-source check — LOCAL

Run on 2026-10-07 against fixed commit `5ec0b7de2`. The later local `main` at record creation, `90df91420`, changed no product UI or shared web path since that commit (`git diff --name-only 5ec0b7de2..90df91420 -- shared/web operations/fleet/fleet/server/web middleware/ui/robot middleware/ui/pilot` was empty). This is a source and host-test result, not a browser-state or device verdict.

| Command | Result | Raw log and SHA-256 |
|---|---|---|
| `python -m pytest shared/web/test/test_palette_gates.py shared/web/test/test_ui_token_contracts.py operations/fleet/test/test_grammar_separation.py middleware/core/gateway/test/test_evidence.py -q -rfE -p no:cacheprovider` | 81 passed; `known_failures.py` 0 NEW | `X:/DevTemp/rosy-site-uiux-current/g1-current.txt` — SHA-256: `3c258768d2e5ed3f39bc8c507ec9372720ccfd73d70c475eb6aba008ceb972a0` |
| `python -m pytest shared/web/test/test_responsive_tiers.py -q -rfE -p no:cacheprovider` | 9 passed; `known_failures.py` 0 NEW | `X:/DevTemp/rosy-site-uiux-current/g1-responsive.txt` — SHA-256: `ace4a64ddfa167e8a3baedd3854c3fdaed7a45d775cd95902481f56cfab875d1` |

D-153 names `test_styleguide.py`, which is absent from the current tree. Its styleguide rendering assertion lives in `shared/web/test/test_ui_token_contracts.py::test_styleguide_renders_the_shared_type_and_interaction_contract` and ran in the 81-test group. The 9 responsive-tier checks enforce the declared width rules. Thus the present G1 machine checks are green at this source snapshot; this result does not prove every active surface's G2 state and width matrix or the user's G3 review.

The [site image recheck](../uiux-site-image-recheck-2026-10-07/result.md) found an older installed Fleet UI. Current candidate installation, real device readback, and G3 remain **HOLD**.
