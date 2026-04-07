"""
Approval Module for TITAN FUSE Protocol.

ITEM-ARCH-07: Release-on-Wait Pattern

Provides approval loop functionality with deadlock prevention.

Author: TITAN FUSE Team
Version: 3.3.0
"""

from .loop import (
    ApprovalLoop,
    ApprovalStatus,
    ApprovalRequest,
    CursorDriftError,
    create_approval_loop
)

__all__ = [
    'ApprovalLoop',
    'ApprovalStatus',
    'ApprovalRequest',
    'CursorDriftError',
    'create_approval_loop',
]
