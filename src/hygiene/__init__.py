"""
TITAN FUSE Protocol - Document Hygiene Module

Implements Phase 5: Document Hygiene Protocol from PROTOCOL.md.

MANDATORY_CLEANUP before final output:
- Remove debug artifacts
- Grep forbidden patterns
- Validate output integrity
"""

from .hygiene_protocol import (
    DocumentHygieneProtocol,
    HygieneResult,
    HygieneCheck
)

__all__ = [
    'DocumentHygieneProtocol',
    'HygieneResult',
    'HygieneCheck'
]
