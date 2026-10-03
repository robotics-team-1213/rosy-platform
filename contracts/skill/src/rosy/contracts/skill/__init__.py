"""ROS-free Skill and PlanBundle contract types (D-427 wave 2a, Q5/Q9).

``rosy.skills.api`` and ``rosy.execution.local.receipts`` re-export these objects
unchanged, so existing imports and JSON shapes stay the same.
"""

from .invocation import SkillInvocation
from .receipts import AttemptIdentity, ReceiptBinding

__all__ = ["AttemptIdentity", "ReceiptBinding", "SkillInvocation"]
