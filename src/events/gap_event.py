"""
GapEvent for TITAN Protocol - PAT-06 compliant serialization.

PAT-06 requires: source, gate, reason, timestamp, severity
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class GapEvent:
    """
    GapEvent represents a deviation or gap in protocol execution.
    
    PAT-06 Compliance:
    - source: Origin of the gap event
    - gate: Gate identifier (e.g., GATE-00, GATE-01)
    - reason: Human-readable reason for the gap
    - timestamp: ISO 8601 timestamp
    - severity: CRITICAL, WARN, INFO, or DEBUG
    """
    source: str
    gate: str
    reason: str
    timestamp: str
    severity: str = "WARN"
    event_id: str = field(default_factory=lambda: f"gap-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        """
        Serialize to JSON string with PAT-06 required fields.
        
        Returns:
            JSON string with all PAT-06 fields
        """
        data = {
            "source": self.source,
            "gate": self.gate,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "event_id": self.event_id,
            "metadata": self.metadata,
        }
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "GapEvent":
        """
        Deserialize from JSON string.
        
        Args:
            json_str: JSON string representation
            
        Returns:
            GapEvent instance
        """
        data = json.loads(json_str)
        return cls(
            source=data["source"],
            gate=data["gate"],
            reason=data["reason"],
            timestamp=data["timestamp"],
            severity=data.get("severity", "WARN"),
            event_id=data.get("event_id", f"gap-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "source": self.source,
            "gate": self.gate,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "event_id": self.event_id,
            "metadata": self.metadata,
        }
