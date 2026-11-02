"""Compatibility import; Account owns this implementation."""
import sys
from rosy_account import password_session as _implementation
sys.modules[__name__] = _implementation
