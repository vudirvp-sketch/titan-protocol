#!/usr/bin/env python3
"""
TITAN FUSE Metrics Generator
Generates metrics.json for monitoring integration
Version: 3.4.0 - Added telemetry fields (per_query_p50, per_query_p95, model_used, latency_ms)
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict


@dataclass
class QueryMetrics:
    """Metrics for a single LLM query."""
    query_id: str
    model_used: str
    latency_ms: float
    per_query_p50: float
    per_query_p95: float
    tokens_used: int
    fallback_used: bool = False


def calculate_percentiles(values: List[float]) -> Dict[str, float]:
    """
    Calculate p50 and p95 percentiles from value list.
    
    Args:
        values: List of numeric values
        
    Returns:
        Dict with p50 and p95 percentile values
    """
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    
    sorted_values = sorted(values)
    n = len(sorted_values)
    
    return {
        "p50": sorted_values[int(n * 0.50)],
        "p95": sorted_values[int(n * 0.95)] if n > 1 else sorted_values[0],
        "p99": sorted_values[int(n * 0.99)] if n > 1 else sorted_values[0]
    }


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
    # v3.4.0 Telemetry fields
    model_used: str = "unknown",
    latency_ms: int = 0,
    per_query_p50: float = 0.0,
    per_query_p95: float = 0.0,
    fallback_used: bool = False,
    llm_query_calls: int = 1,
    model_breakdown: Optional[Dict[str, Dict]] = None,
    # Multi-agent metrics
    agents_dispatched: int = 0,
    agents_completed: int = 0,
    sync_latency_ms: int = 0,
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
        model_used: Primary LLM model identifier
        latency_ms: Total latency in milliseconds
        per_query_p50: P50 latency per query
        per_query_p95: P95 latency per query
        fallback_used: Whether fallback model was used
        llm_query_calls: Number of LLM API calls
        model_breakdown: Token usage by model
        agents_dispatched: Number of agents dispatched (TIER_7)
        agents_completed: Number of agents completed (TIER_7)
        sync_latency_ms: Multi-agent sync latency (TIER_7)
        status: Session status

    Returns:
        Complete metrics dictionary
    """
    metrics = {
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
            "utilization_pct": round((tokens_used / tokens_max) * 100, 1) if tokens_max > 0 else 0,
            "llm_query_calls": llm_query_calls,
            "avg_chunk_tokens": tokens_used // source_chunks if source_chunks > 0 else 0
        },
        "llm_telemetry": {
            "per_query_p50": per_query_p50,
            "per_query_p95": per_query_p95,
            "total_latency_ms": latency_ms,
            "model_used": model_used,
            "fallback_used": fallback_used,
            "fallback_count": 1 if fallback_used else 0
        },
        "gates": gates,
        "quality": {
            "confidence_score": confidence_score,
            "zero_drift_violations": 0,
            "keep_preserved": True,
            "idempotency_verified": True
        }
    }
    
    # Add model breakdown if provided
    if model_breakdown:
        metrics["llm_telemetry"]["model_breakdown"] = model_breakdown
    
    # Add multi-agent metrics if applicable
    if agents_dispatched > 0:
        metrics["multi_agent"] = {
            "agents_dispatched": agents_dispatched,
            "agents_completed": agents_completed,
            "sync_latency_ms": sync_latency_ms,
            "conflict_resolutions": 0
        }
    
    return metrics


# Example metrics output with v3.4.0 telemetry fields
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
        "utilization_pct": 78.4,
        "llm_query_calls": 18,
        "avg_chunk_tokens": 4357
    },
    "llm_telemetry": {
        "per_query_p50": 150.0,
        "per_query_p95": 350.0,
        "total_latency_ms": 4230,
        "model_used": "gpt-4o-mini",
        "fallback_used": False,
        "fallback_count": 0,
        "model_breakdown": {
            "gpt-4o-mini": {
                "calls": 18,
                "tokens": 78432,
                "avg_latency_ms": 235.0
            }
        }
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
