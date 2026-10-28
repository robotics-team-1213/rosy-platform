"""Fixed standalone UI asset set; source files remain in their canonical owners."""

from pathlib import Path
import shutil
import tempfile


COMMON = ('tokens.css', 'components.css', 'app-shell.css', 'theme.js', 'core_ui_logic.js',
          'ui.js', 'ui-wiring.js', 'confirmation.js', 'live-dialog-geometry.js')
ASSETS = {'/': 'index.html', '/monitoring.js': 'monitoring.js', '/monitoring.css': 'monitoring.css',
          **{f'/common/{name}': f'common/{name}' for name in COMMON}}


def build_web(repo: Path, output: Path):
    """Publish a new bundle without replacing an existing destination."""
    repo, output = repo.resolve(strict=True), output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    sources = {}
    for name in ASSETS.values():
        owner = repo / ('shared/web' if name.startswith('common/') else 'applications/monitoring/web')
        source = (owner / Path(name).name).resolve(strict=True)
        if not source.is_relative_to(owner.resolve(strict=True)) or not source.is_file():
            raise ValueError('invalid monitoring asset')
        sources[name] = source
    with tempfile.TemporaryDirectory(prefix='.monitoring-web-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'web'
        (stage / 'common').mkdir(parents=True)
        for name, source in sources.items():
            shutil.copyfile(source, stage / name)
        stage.rename(output)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Build a standalone Monitoring UI from a ROSY checkout')
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build_web(args.repo, args.output)
