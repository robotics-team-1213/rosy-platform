## 2026-11-21 · uncommitted · Robot 3D assets: vendored three.js, OMX and Pinky meshes, asset boundary (slice S3 of #378)

- 변경: Add shared/web/meshes (12 files + SOURCE.json), vendor/three.* (MIT) and tools/robot_meshes.py; list them in shared-assets.json and CMakeLists; allow shared/web/meshes in test_3d_asset_boundary
- 증거: pyflakes, harness lint, lab affected run (test_asset_manifest, test_3d_asset_boundary); see PR body
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
