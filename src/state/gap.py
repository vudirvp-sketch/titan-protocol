"""
Structured Gap representation.
Replaces string-based gap markers.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
import hashlib
import re


class GapSeverity(Enum):
    SEV_1 = "SEV-1"  # Critical - blocks release
    SEV_2 = "SEV-2"  # High - should be fixed
    SEV_3 = "SEV-3"  # Medium - nice to fix
    SEV_4 = "SEV-4"  # Low - minor issue


@dataclass
class Gap:
    """
    Structured representation of a gap.
    
    A gap indicates something that could not be verified or completed.
    """
    id: str
    reason: str
    severity: GapSeverity = GapSeverity.SEV_4
    
    # Source reference
    source_file: Optional[str] = None
    source_line_start: Optional[int] = None
    source_line_end: Optional[int] = None
    
    # Verification
    source_checksum: Optional[str] = None
    verified: bool = False
    
    # Metadata
    context: str = ""
    suggested_action: str = ""
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique gap ID."""
        content = f"{self.reason}{self.source_file}{self.source_line_start}"
        return f"GAP-{hashlib.md5(content.encode()).hexdigest()[:8].upper()}"
    
    def to_string(self) -> str:
        """Convert to legacy string format for compatibility."""
        checksum_part = ""
        if self.source_checksum:
            checksum_part = f" -- source:{self.source_line_start}-{self.source_line_end}:{self.source_checksum}"
        
        return f"[gap: {self.reason} ({self.severity.value}){checksum_part}]"
    
    @classmethod
    def from_string(cls, gap_str: str) -> "Gap":
        """Parse legacy gap string."""
        # Extract reason
        match = re.search(r'\[gap:\s*([^\]]+)\]', gap_str)
        if not match:
            return cls(id="", reason=gap_str)
        
        content = match.group(1)
        
        # Extract severity
        severity = GapSeverity.SEV_4
        for sev in GapSeverity:
            if sev.value in content:
                severity = sev
                break
        
        # Extract source reference
        source_match = re.search(r'source:(\d+)-(\d+):([a-f0-9]+)', content)
        source_file = None
        line_start = None
        line_end = None
        checksum = None
        
        if source_match:
            line_start = int(source_match.group(1))
            line_end = int(source_match.group(2))
            checksum = source_match.group(3)
        
        # Clean reason
        reason = re.sub(r'\s*--\s*source:.*$', '', content)
        reason = re.sub(r'\s*\([A-Z]+-\d+\)\s*$', '', reason).strip()
        
        return cls(
            id="",
            reason=reason,
            severity=severity,
            source_line_start=line_start,
            source_line_end=line_end,
            source_checksum=checksum,
            verified=bool(checksum)
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "reason": self.reason,
            "severity": self.severity.value,
            "source_file": self.source_file,
            "source_line_start": self.source_line_start,
            "source_line_end": self.source_line_end,
            "source_checksum": self.source_checksum,
            "verified": self.verified,
            "context": self.context,
            "suggested_action": self.suggested_action,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Gap":
        """Create from dictionary."""
        return cls(
            id=data.get("id", ""),
            reason=data.get("reason", ""),
            severity=GapSeverity(data.get("severity", "SEV-4")),
            source_file=data.get("source_file"),
            source_line_start=data.get("source_line_start"),
            source_line_end=data.get("source_line_end"),
            source_checksum=data.get("source_checksum"),
            verified=data.get("verified", False),
            context=data.get("context", ""),
            suggested_action=data.get("suggested_action", ""),
            tags=data.get("tags", [])
        )


def convert_gaps_to_objects(gap_strings: List[str]) -> List[Gap]:
    """Convert list of gap strings to Gap objects."""
    return [Gap.from_string(s) for s in gap_strings]


def convert_gaps_to_strings(gaps: List[Gap]) -> List[str]:
    """Convert list of Gap objects to strings."""
    return [g.to_string() for g in gaps]
