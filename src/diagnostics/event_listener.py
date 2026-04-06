"""
Diagnostics Event Listener for TITAN FUSE Protocol.

Listens to gate failures and provides diagnostic analysis
with automatic escalation to human review.

Author: TITAN FUSE Team
Version: 3.2.3
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import logging


@dataclass
class DiagnosticResult:
    """Result of diagnostic analysis."""
    action: str
    cause: str
    symptom: str
    occurrences: int
    gap: Optional[str] = None
    escalation_required: bool = False
    suggested_fix: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "action": self.action,
            "cause": self.cause,
            "symptom": self.symptom,
            "occurrences": self.occurrences,
            "gap": self.gap,
            "escalation_required": self.escalation_required,
            "suggested_fix": self.suggested_fix
        }


class DiagnosticsListener:
    """
    Listen to gate failures and diagnose patterns.

    Provides:
    - Automatic diagnosis of failure patterns
    - Escalation to human review on repeated failures
    - Symptom tracking and history

    Usage:
        listener = DiagnosticsListener()

        # Subscribe to EventBus
        bus.subscribe("GATE_FAIL", listener.on_event)

        # Or call directly
        result = listener.on_gate_fail(event)
        if result.escalation_required:
            print(f"Escalating: {result.gap}")
    """

    DEFAULT_RULES = {
        "gate_fail_patterns": {
            "GATE-00": {
                "symptoms": {
                    "nav_map_missing": {
                        "cause": "chunking_failed",
                        "action": "rechunk",
                        "suggested_fix": "Verify file is valid text and retry chunking"
                    },
                    "index_incomplete": {
                        "cause": "incomplete_scan",
                        "action": "rescan",
                        "suggested_fix": "Check for encoding issues or large binary sections"
                    }
                }
            },
            "GATE-01": {
                "symptoms": {
                    "pattern_not_found": {
                        "cause": "invalid_pattern",
                        "action": "update_pattern",
                        "suggested_fix": "Review target patterns in configuration"
                    },
                    "scan_timeout": {
                        "cause": "file_too_large",
                        "action": "reduce_chunk_size",
                        "suggested_fix": "Reduce chunk size in config.yaml"
                    }
                }
            },
            "GATE-02": {
                "symptoms": {
                    "unclassified_issue": {
                        "cause": "unknown_pattern",
                        "action": "manual_review",
                        "suggested_fix": "Add issue to pathology registry for analysis"
                    }
                }
            },
            "GATE-03": {
                "symptoms": {
                    "plan_invalid": {
                        "cause": "dependency_cycle",
                        "action": "replan",
                        "suggested_fix": "Review batch dependencies for cycles"
                    },
                    "keep_veto_violation": {
                        "cause": "protected_content",
                        "action": "exclude",
                        "suggested_fix": "Remove KEEP_VETO items from execution plan"
                    }
                }
            },
            "GATE-04": {
                "symptoms": {
                    "checksum_mismatch": {
                        "cause": "source_modified",
                        "action": "rescan",
                        "suggested_fix": "Source file was modified. Restart session."
                    },
                    "validation_failed": {
                        "cause": "invalid_patch",
                        "action": "retry_with_context",
                        "suggested_fix": "Apply patch with more context lines"
                    },
                    "sev1_gaps_exceeded": {
                        "cause": "critical_issues",
                        "action": "fix_sev1_first",
                        "suggested_fix": "Address SEV-1 issues before continuing"
                    },
                    "sev2_gaps_exceeded": {
                        "cause": "high_priority_issues",
                        "action": "fix_sev2_first",
                        "suggested_fix": "Reduce SEV-2 gaps to <= 2"
                    }
                }
            },
            "GATE-05": {
                "symptoms": {
                    "artifacts_missing": {
                        "cause": "generation_failed",
                        "action": "regenerate",
                        "suggested_fix": "Re-run artifact generation"
                    },
                    "hygiene_failed": {
                        "cause": "cleanup_error",
                        "action": "manual_cleanup",
                        "suggested_fix": "Run document hygiene manually"
                    }
                }
            }
        }
    }

    def __init__(self, rules_path: Path = None, max_identical_symptoms: int = 3):
        """
        Initialize DiagnosticsListener.

        Args:
            rules_path: Path to YAML file with diagnostic rules
            max_identical_symptoms: Max identical symptoms before escalation
        """
        self.rules = self._load_rules(rules_path)
        self.symptom_counts: Dict[str, int] = defaultdict(int)
        self.max_identical_symptoms = max_identical_symptoms
        self._logger = logging.getLogger(__name__)
        self._symptom_history: List[Dict] = []

    def _load_rules(self, path: Path) -> Dict:
        """Load diagnostic rules from YAML."""
        if path and path.exists():
            try:
                with open(path) as f:
                    return yaml.safe_load(f)
            except Exception as e:
                self._logger.warning(f"Failed to load rules from {path}: {e}")
        return self.DEFAULT_RULES

    def on_gate_fail(self, event) -> DiagnosticResult:
        """
        Handle GATE_FAIL event.

        Args:
            event: Event object with gate failure data

        Returns:
            DiagnosticResult with analysis and recommended action
        """
        gate_id = event.data.get("gate_id", "UNKNOWN")
        reason = event.data.get("reason", "unknown")
        details = event.data.get("details", {})

        symptom_key = f"{gate_id}:{reason}"
        self.symptom_counts[symptom_key] += 1

        # Record history
        self._symptom_history.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "gate_id": gate_id,
            "reason": reason,
            "count": self.symptom_counts[symptom_key],
            "details": details
        })

        # Check if escalation needed
        if self.symptom_counts[symptom_key] >= self.max_identical_symptoms:
            self._logger.warning(
                f"Escalation required: {symptom_key} occurred "
                f"{self.symptom_counts[symptom_key]} times"
            )
            return DiagnosticResult(
                action="escalate",
                cause="repeated_failure",
                symptom=symptom_key,
                occurrences=self.symptom_counts[symptom_key],
                gap="[gap: human_review_required]",
                escalation_required=True,
                suggested_fix="Multiple identical failures detected. Human intervention required."
            )

        # Apply diagnostic rule
        rule = self.rules.get("gate_fail_patterns", {}).get(gate_id, {})
        symptom_rule = rule.get("symptoms", {}).get(reason, {})

        return DiagnosticResult(
            action=symptom_rule.get("action", "retry"),
            cause=symptom_rule.get("cause", "unknown"),
            symptom=symptom_key,
            occurrences=self.symptom_counts[symptom_key],
            suggested_fix=symptom_rule.get("suggested_fix")
        )

    def on_event(self, event) -> Optional[DiagnosticResult]:
        """
        Generic event handler for EventBus subscription.

        Args:
            event: Event object

        Returns:
            DiagnosticResult for GATE_FAIL events, None otherwise
        """
        if event.event_type == "GATE_FAIL":
            return self.on_gate_fail(event)
        return None

    def get_symptom_report(self) -> Dict:
        """
        Get comprehensive symptom report.

        Returns:
            Dict with symptom counts, totals, and recent history
        """
        return {
            "symptom_counts": dict(self.symptom_counts),
            "total_failures": sum(self.symptom_counts.values()),
            "unique_symptoms": len(self.symptom_counts),
            "escalation_threshold": self.max_identical_symptoms,
            "symptoms_near_escalation": [
                {"symptom": s, "count": c}
                for s, c in self.symptom_counts.items()
                if c >= self.max_identical_symptoms - 1
            ],
            "history": self._symptom_history[-20:]  # Last 20 events
        }

    def get_most_common_symptom(self) -> Optional[Dict]:
        """Get the most common symptom."""
        if not self.symptom_counts:
            return None
        most_common = max(self.symptom_counts.items(), key=lambda x: x[1])
        return {"symptom": most_common[0], "count": most_common[1]}

    def get_gate_failure_summary(self) -> Dict[str, int]:
        """Get failure count per gate."""
        gate_counts: Dict[str, int] = defaultdict(int)
        for symptom, count in self.symptom_counts.items():
            gate_id = symptom.split(":")[0]
            gate_counts[gate_id] += count
        return dict(gate_counts)

    def reset(self) -> None:
        """Reset symptom tracking."""
        self.symptom_counts.clear()
        self._symptom_history.clear()
        self._logger.info("Diagnostics tracking reset")

    def add_custom_rule(self, gate_id: str, symptom: str,
                        cause: str, action: str,
                        suggested_fix: str = None) -> None:
        """Add custom diagnostic rule."""
        if "gate_fail_patterns" not in self.rules:
            self.rules["gate_fail_patterns"] = {}
        if gate_id not in self.rules["gate_fail_patterns"]:
            self.rules["gate_fail_patterns"][gate_id] = {"symptoms": {}}

        self.rules["gate_fail_patterns"][gate_id]["symptoms"][symptom] = {
            "cause": cause,
            "action": action
        }
        if suggested_fix:
            self.rules["gate_fail_patterns"][gate_id]["symptoms"][symptom]["suggested_fix"] = suggested_fix
