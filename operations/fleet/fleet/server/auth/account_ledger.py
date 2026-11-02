"""Compatibility import; Account owns this implementation."""
import sys
from rosy_account import account_ledger as _implementation
sys.modules[__name__] = _implementation
