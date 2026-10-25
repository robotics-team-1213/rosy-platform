"""Run one unprivileged, loopback-only Monitoring process."""

import argparse
import os
from pathlib import Path
import sys

import uvicorn

from .config import load_config, load_credentials
from .service import Collector, create_app
from .store import MonitoringStore


def main(argv=None):
    parser = argparse.ArgumentParser(prog='rosy-monitoring')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8786)
    parser.add_argument('--web-root', type=Path)
    options = parser.parse_args(argv)
    if not 1 <= options.port <= 65535:
        parser.error('port must be between 1 and 65535')
    store = None
    try:
        if os.name != 'posix':
            raise ValueError()
        config = load_config(options.config)
        credentials = load_credentials(config, os.environ)
        state = options.state_dir
        if not state.is_absolute() or state.is_symlink():
            raise ValueError()
        state.mkdir(mode=0o700, exist_ok=True)
        if not state.is_dir() or state.stat().st_mode & 0o077:
            raise ValueError()
        store = MonitoringStore(state / 'monitoring.sqlite3', config.collector_id)
        collector = Collector(config, credentials, store)
        app = create_app(collector, web_root=options.web_root)
    except Exception:
        if store is not None:
            store.close()
        print('MONITORING_STARTUP_FAILED', file=sys.stderr)
        return 1
    try:
        uvicorn.run(app, host='127.0.0.1', port=options.port, workers=1, access_log=False,
                    limit_concurrency=32, timeout_graceful_shutdown=5)
    finally:
        store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
