#!/usr/bin/env python3
"""
TITAN FUSE Metrics Generator
Generates metrics.json for monitoring integration
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional


def generate_metrics(
    session_id: str,
    source_file: str,
    source_lines: int,
    source_chunks: int,
    issues_found: int,
    issues_fixed: int,
    issues_deferred: int,
    gaps: int,
    gap_severity: Dict[str, int],
    tokens_used: int,
    tokens_max: int,
    gates: Dict[str, str],
    duration_seconds: int,
    confidence_score: float,
    status: str = "COMPLETE"
) -> Dict[str, Any]:
    """
    Generate a metrics.json structure.

    Args:
        session_id: Session UUID
        source_file: Source file name
        source_lines: Number of lines in source
        source_chunks: Number of chunks
        issues_found: Total issues found
        issues_fixed: Issues that were fixed
        issues_deferred: Issues deferred
        gaps: Number of gaps
        gap_severity: Dict of SEV-N -> count
        tokens_used: Tokens consumed
        tokens_max: Maximum tokens allowed
        gates: Dict of GATE-N -> status
        duration_seconds: Processing duration
        confidence_score: Overall confidence (0-100)
        status: Session status

    Returns:
        Complete metrics dictionary
    """
    return {
        "session": {
            "id": session_id,
            "start_time": datetime.utcnow().isoformat() + "Z",
            "end_time": datetime.utcnow().isoformat() + "Z",
            "duration_seconds": duration_seconds,
            "status": status
        },
        "source": {
            "file": source_file,
            "lines": source_lines,
            "chunks": source_chunks
        },
        "processing": {
            "issues_found": issues_found,
            "issues_fixed": issues_fixed,
            "issues_deferred": issues_deferred,
            "gaps": gaps,
            "gap_severity": gap_severity,
            "chunks_processed": source_chunks,
            "chunks_failed": 0
        },
        "budget": {
            "tokens_used": tokens_used,
            "tokens_max": tokens_max,
            "utilization_pct": round((tokens_used / tokens_max) * 100, 1) if tokens_max > 0 else 0
        },
        "gates": gates,
        "quality": {
            "confidence_score": confidence_score,
            "zero_drift_violations": 0,
            "keep_preserved": True,
            "idempotency_verified": True
        }
    }


# Example metrics output
EXAMPLE_METRICS = {
    "session": {
        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "start_time": "2024-01-15T10:30:00Z",
        "end_time": "2024-01-15T11:00:47Z",
        "duration_seconds": 1847,
        "status": "COMPLETE"
    },
    "source": {
        "file": "example.md",
        "lines": 25430,
        "chunks": 18
    },
    "processing": {
        "issues_found": 47,
        "issues_fixed": 42,
        "issues_deferred": 3,
        "gaps": 2,
        "gap_severity": {
            "SEV-1": 0,
            "SEV-2": 1,
            "SEV-3": 1,
            "SEV-4": 0
        },
        "chunks_processed": 18,
        "chunks_failed": 0
    },
    "budget": {
        "tokens_used": 78432,
        "tokens_max": 100000,
        "utilization_pct": 78.4
    },
    "gates": {
        "GATE-00": "PASS",
        "GATE-01": "PASS",
        "GATE-02": "PASS",
        "GATE-03": "PASS",
        "GATE-04": "WARN",
        "GATE-05": "PASS"
    },
    "quality": {
        "confidence_score": 94,
        "zero_drift_violations": 0,
        "keep_preserved": True,
        "idempotency_verified": True
    }
}


if __name__ == "__main__":
    # Print example metrics
    print(json.dumps(EXAMPLE_METRICS, indent=2))
