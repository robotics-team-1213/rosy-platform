"""Compatibility import; Account owns this implementation."""
import sys
from rosy_account import site_users as _implementation
if __name__ == '__main__':
    raise SystemExit(_implementation.main(sys.argv[1:]))
sys.modules[__name__] = _implementation
