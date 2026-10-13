"""Exercise the actual Android token exporter without an SDK or Android plugin."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(os.environ.get("ROSY_RUN_NATIVE_TOKEN_TESTS") != "1",
                    reason="enable existing Gradle wrapper generation on a remote test PC")
def test_native_export_tracks_canonical_tokens_and_rejects_non_scalar_roles(tmp_path):
    assert shutil.which("java"), "Native generation requires the existing JDK 17 toolchain"
    canonical = tmp_path / "tokens.css"
    css = (ROOT / "shared/web/tokens.css").read_text(encoding="utf-8")
    canonical.write_text(css, encoding="utf-8")
    exporter = ROOT / "shared/web/native-tokens.gradle"
    (tmp_path / "settings.gradle").write_text("rootProject.name = 'token-export'\n", encoding="utf-8")
    (tmp_path / "build.gradle").write_text(
        "ext.rosyTokenSource = 'tokens.css'\next.rosyTokenPackage = 'rosy.fixture'\n"
        "ext.android = [sourceSets: [getByName: { name -> [java: [srcDir: { path -> }]] }]]\n"
        "tasks.register('preBuild')\n"
        f"apply from: '{exporter.as_posix()}'\n", encoding="utf-8")
    command = ["bash", str(ROOT / "operations/ui/cam/gradlew"), "--project-dir", str(tmp_path),
               "generateNativeTokens", "--no-daemon", "--console=plain"]

    def run():
        return subprocess.run(command, capture_output=True, text=True, timeout=300)

    first = run()
    assert first.returncode == 0, first.stdout + first.stderr
    folder = tmp_path / "build/generated/rosy-tokens/rosy/fixture"
    metrics = (folder / "RosyMetrics.kt").read_text()
    colours = (folder / "RosyTokenColors.kt").read_text()
    assert "TextLabel = 14.0f" in metrics and "TargetSecondary = 48.0f" in metrics
    assert "InsetButton = 12.0f" in metrics and "Line14Alpha = 0.14f" in metrics
    assert "Ground = 0xFF101214.toInt()" in colours
    canonical.write_text(css.replace("--space-3: 12px;", "--space-3: 16px;"), encoding="utf-8")
    second = run()
    assert second.returncode == 0, second.stdout + second.stderr
    assert "InsetButton = 16.0f" in (folder / "RosyMetrics.kt").read_text()
    canonical.write_text(css.replace("--text-label: 0.875rem;", "--text-label: invalid;"), encoding="utf-8")
    invalid = run()
    assert invalid.returncode != 0 and "Non-scalar canonical token --text-label" in invalid.stdout + invalid.stderr
