"""Standalone Kit CLI exit after runner cleanup, without a Python thread join.

SimulationApp.close() can return while SDK-owned Python threads remain alive.
Only script entrypoints use this terminal process exit; imported main() keeps
raising its original exceptions. Never let Kit's default exit(0) mask errors.
"""

import os
import sys
import traceback


def run_cli(main, exit_process=os._exit):
    status = 0
    try:
        main()  # Its finally block must zero output and close the SDK first.
    except KeyboardInterrupt:
        status = 130
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
    except BaseException:
        status = 1
        traceback.print_exc()
    finally:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except BaseException:
                # An unwritten diagnostic must not become a successful receipt.
                # Still flush the other stream and preserve an existing failure.
                status = status or 1
        # Bypass interpreter joins only after the actual runner has returned
        # or finished its exception cleanup. The original status is preserved.
        exit_process(status)
