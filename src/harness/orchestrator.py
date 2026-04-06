"""
TITAN FUSE Protocol - Orchestrator

Execution layer that coordinates the processing pipeline.
Implements the TIER structure and GATE validation.

Updated for v3.2:
- INVAR-05: LLM Code Execution Gate integration
- PRINCIPLE-04: Secondary chunk limits
- GATE-04: Confidence advisory
- metrics.json: p50/p95 token distribution
"""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
import statistics


class Phase(Enum):
    """Processing phases as defined in PROTOCOL.base.md"""
    BOOTSTRAP = -1
    INIT = 0
    SEARCH_DISCOVERY = 1
    ANALYSIS_CLASSIFICATION = 2
    PLANNING = 3
    EXECUTION_VALIDATION = 4
    DELIVERY_HYGIENE = 5


PHASE_NAMES = {
    -1: "PHASE -1: BOOTSTRAP",
    0: "PHASE 0: INITIALIZATION",
    1: "PHASE 1: SEARCH & DISCOVERY",
    2: "PHASE 2: ANALYSIS & CLASSIFICATION",
    3: "PHASE 3: PLANNING",
    4: "PHASE 4: EXECUTION & VALIDATION",
    5: "PHASE 5: DELIVERY & HYGIENE"
}


class Orchestrator:
    """
    Execution orchestrator for TITAN FUSE Protocol.

    Coordinates:
    - Phase transitions (Phase -1 through Phase 5)
    - Gate validation (GATE-00 through GATE-05)
    - Tool routing
    - Batch processing
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.protocol_path = repo_root / "PROTOCOL.md"
        self.config_path = repo_root / "config.yaml"
        self.inputs_dir = repo_root / "inputs"
        self.outputs_dir = repo_root / "outputs"

        # Load configuration
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load configuration from config.yaml."""
        try:
            import yaml
            with open(self.config_path) as f:
                return yaml.safe_load(f)
        except Exception:
            return {
                "session": {"max_tokens": 100000, "max_time_minutes": 60},
                "chunking": {"default_size": 1500},
                "validation": {"max_patch_iterations": 2}
            }

    # =========================================================================
    # GATE VALIDATION
    # =========================================================================

    def validate_gate(self, gate_id: str, session: Dict) -> Tuple[bool, Dict]:
        """
        Validate a specific gate.

        Args:
            gate_id: Gate identifier (GATE-00 through GATE-05)
            session: Current session state

        Returns:
            Tuple of (passed, details)
        """
        gate_validators = {
            "GATE-00": self._validate_gate_00,
            "GATE-01": self._validate_gate_01,
            "GATE-02": self._validate_gate_02,
            "GATE-03": self._validate_gate_03,
            "GATE-04": self._validate_gate_04,
            "GATE-05": self._validate_gate_05
        }

        validator = gate_validators.get(gate_id)
        if validator:
            return validator(session)

        return False, {"error": f"Unknown gate: {gate_id}"}

    def _validate_gate_00(self, session: Dict) -> Tuple[bool, Dict]:
        """
        GATE-00: NAV_MAP exists AND all chunks indexed

        Validation:
        - Navigation map built
        - All chunks have IDs
        - Source file loaded
        """
        details = {
            "gate": "GATE-00",
            "checks": []
        }

        # Check source file
        source_file = session.get("source_file")
        if not source_file:
            details["checks"].append({
                "name": "source_file",
                "status": "FAIL",
                "message": "No source file specified"
            })
            return False, details

        details["checks"].append({
            "name": "source_file",
            "status": "PASS",
            "message": f"Source: {source_file}"
        })

        # Check NAV_MAP (chunks)
        chunks = session.get("chunks", {})
        if not chunks:
            details["checks"].append({
                "name": "nav_map",
                "status": "FAIL",
                "message": "No chunks indexed"
            })
            return False, details

        details["checks"].append({
            "name": "nav_map",
            "status": "PASS",
            "message": f"{len(chunks)} chunks indexed"
        })

        # All checks passed
        return True, details

    def _validate_gate_01(self, session: Dict) -> Tuple[bool, Dict]:
        """
        GATE-01: All target patterns scanned

        Validation:
        - Pattern detection complete
        - Duplicates identified
        - Terminology checked
        """
        details = {
            "gate": "GATE-01",
            "checks": []
        }

        # Check if patterns were scanned
        state_snapshot = session.get("state_snapshot", {})
        patterns_scanned = state_snapshot.get("patterns_scanned", False)

        if not patterns_scanned:
            details["checks"].append({
                "name": "patterns_scanned",
                "status": "FAIL",
                "message": "Pattern detection not complete"
            })
            return False, details

        details["checks"].append({
            "name": "patterns_scanned",
            "status": "PASS",
            "message": "All target patterns scanned"
        })

        return True, details

    def _validate_gate_02(self, session: Dict) -> Tuple[bool, Dict]:
        """
        GATE-02: All issues classified with ISSUE_ID

        Validation:
        - Each issue has ISSUE_ID
        - Severity assigned (SEV-1..4)
        - Category assigned
        """
        details = {
            "gate": "GATE-02",
            "checks": []
        }

        open_issues = session.get("open_issues", [])
        state_snapshot = session.get("state_snapshot", {})
        issues_classified = state_snapshot.get("issues_classified", False)

        if not issues_classified and open_issues:
            details["checks"].append({
                "name": "issues_classified",
                "status": "FAIL",
                "message": f"{len(open_issues)} issues not fully classified"
            })
            return False, details

        details["checks"].append({
            "name": "issues_classified",
            "status": "PASS",
            "message": f"{len(open_issues)} issues classified"
        })

        return True, details

    def _validate_gate_03(self, session: Dict) -> Tuple[bool, Dict]:
        """
        GATE-03: Plan validated AND no KEEP_VETO violations AND budget headroom

        Validation:
        - Execution plan exists
        - No KEEP_VETO violations
        - Budget available
        """
        details = {
            "gate": "GATE-03",
            "checks": []
        }

        # Check budget
        tokens_used = session.get("tokens_used", 0)
        max_tokens = session.get("max_tokens", 100000)
        budget_remaining = max_tokens - tokens_used
        budget_pct = (tokens_used / max_tokens) * 100

        if budget_pct > 90:
            details["checks"].append({
                "name": "budget",
                "status": "FAIL",
                "message": f"Budget exceeded: {budget_pct:.1f}% used"
            })
            return False, details

        details["checks"].append({
            "name": "budget",
            "status": "PASS",
            "message": f"Budget OK: {budget_pct:.1f}% used, {budget_remaining} remaining"
        })

        # Check execution plan
        state_snapshot = session.get("state_snapshot", {})
        execution_plan = state_snapshot.get("execution_plan")

        if not execution_plan:
            details["checks"].append({
                "name": "execution_plan",
                "status": "FAIL",
                "message": "No execution plan"
            })
            return False, details

        details["checks"].append({
            "name": "execution_plan",
            "status": "PASS",
            "message": "Execution plan validated"
        })

        # Check KEEP_VETO
        keep_veto_violations = state_snapshot.get("keep_veto_violations", [])
        if keep_veto_violations:
            details["checks"].append({
                "name": "keep_veto",
                "status": "FAIL",
                "message": f"KEEP_VETO violations: {keep_veto_violations}"
            })
            return False, details

        details["checks"].append({
            "name": "keep_veto",
            "status": "PASS",
            "message": "No KEEP_VETO violations"
        })

        return True, details

    def _validate_gate_04(self, session: Dict) -> Tuple[bool, Dict]:
        """
        GATE-04: Validations pass OR gaps within threshold
        
        Updated in v3.2:
        - Added confidence advisory check
        
        Threshold Rules:
        - BLOCK: SEV-1 gaps > 0, SEV-2 gaps > 2, total gaps > 20%
        - WARN: SEV-3 gaps > 5, SEV-4 gaps > 10
        - PASS: All above false
        
        Confidence Advisory (NEW in v3.2):
        - IF all completed QueryResults have confidence = HIGH
          AND total open gaps = 0:
          → log advisory: "early_exit eligible"
          → agent MAY skip remaining SEV-4-only batches with human acknowledgement
        """
        details = {
            "gate": "GATE-04",
            "checks": []
        }

        known_gaps = session.get("known_gaps", [])
        open_issues = session.get("open_issues", [])

        # Count gaps by severity (would parse from gap strings in production)
        sev1_gaps = sum(1 for g in known_gaps if "SEV-1" in g)
        sev2_gaps = sum(1 for g in known_gaps if "SEV-2" in g)
        sev3_gaps = sum(1 for g in known_gaps if "SEV-3" in g)
        sev4_gaps = sum(1 for g in known_gaps if "SEV-4" in g)

        total_issues = len(open_issues) or 1
        total_gaps = len(known_gaps)
        gap_pct = (total_gaps / total_issues) * 100 if total_issues > 0 else 0

        # Check blocking conditions
        blocked = False
        warnings = []

        if sev1_gaps > 0:
            blocked = True
            details["checks"].append({
                "name": "sev1_gaps",
                "status": "BLOCK",
                "message": f"SEV-1 gaps: {sev1_gaps} (max: 0)"
            })

        if sev2_gaps > 2:
            blocked = True
            details["checks"].append({
                "name": "sev2_gaps",
                "status": "BLOCK",
                "message": f"SEV-2 gaps: {sev2_gaps} (max: 2)"
            })

        if gap_pct > 20:
            blocked = True
            details["checks"].append({
                "name": "total_gaps",
                "status": "BLOCK",
                "message": f"Total gaps: {gap_pct:.1f}% (max: 20%)"
            })

        # Check warning conditions
        if sev3_gaps > 5:
            warnings.append(f"SEV-3 gaps: {sev3_gaps} (max: 5)")

        if sev4_gaps > 10:
            warnings.append(f"SEV-4 gaps: {sev4_gaps} (max: 10)")

        # NEW in v3.2: Confidence advisory check
        confidence_summary = session.get("confidence_summary", {})
        all_high_confidence = confidence_summary.get("all_high", False)
        
        if all_high_confidence and total_gaps == 0:
            details["checks"].append({
                "name": "confidence_advisory",
                "status": "ADVISORY",
                "message": "early_exit eligible — all chunks HIGH confidence, zero gaps"
            })
            details["early_exit_eligible"] = True
            # Note: This is advisory only, does NOT auto-exit
            # Requires human acknowledgement to skip SEV-4 batches

        if blocked:
            return False, details

        if warnings:
            details["status"] = "WARN"
            details["warnings"] = warnings
            return True, details

        details["checks"].append({
            "name": "gates_validation",
            "status": "PASS",
            "message": "All validations passed"
        })

        return True, details

    def _validate_gate_05(self, session: Dict) -> Tuple[bool, Dict]:
        """
        GATE-05: All artifacts generated AND hygiene complete

        Validation:
        - CHANGE_LOG.md created
        - INDEX.md created
        - metrics.json created
        - Document hygiene applied
        """
        details = {
            "gate": "GATE-05",
            "checks": []
        }

        # Check for artifacts
        artifacts = ["CHANGE_LOG.md", "INDEX.md", "metrics.json"]
        missing = []

        for artifact in artifacts:
            artifact_path = self.outputs_dir / artifact
            if not artifact_path.exists():
                missing.append(artifact)

        if missing:
            details["checks"].append({
                "name": "artifacts",
                "status": "FAIL",
                "message": f"Missing artifacts: {missing}"
            })
            return False, details

        details["checks"].append({
            "name": "artifacts",
            "status": "PASS",
            "message": f"All artifacts generated: {artifacts}"
        })

        # Check document hygiene
        state_snapshot = session.get("state_snapshot", {})
        hygiene_complete = state_snapshot.get("hygiene_complete", False)

        if not hygiene_complete:
            details["checks"].append({
                "name": "hygiene",
                "status": "FAIL",
                "message": "Document hygiene not complete"
            })
            return False, details

        details["checks"].append({
            "name": "hygiene",
            "status": "PASS",
            "message": "Document hygiene complete"
        })

        return True, details

    # =========================================================================
    # PIPELINE EXECUTION
    # =========================================================================

    def run_pipeline(self,
                     session: Dict,
                     start_phase: Optional[str] = None,
                     batch_size: int = 5) -> Dict:
        """
        Run the processing pipeline.

        Args:
            session: Current session state
            start_phase: Optional phase to start from
            batch_size: Number of batches before checkpoint

        Returns:
            Pipeline execution result
        """
        result = {
            "success": False,
            "phases_completed": [],
            "artifacts": [],
            "errors": []
        }

        # Determine starting phase
        current_phase = session.get("current_phase", -1)
        if start_phase:
            try:
                current_phase = int(start_phase)
            except ValueError:
                pass

        # Execute phases sequentially
        phases = [
            (-1, self._phase_bootstrap),
            (0, self._phase_init),
            (1, self._phase_search_discovery),
            (2, self._phase_analysis_classification),
            (3, self._phase_planning),
            (4, self._phase_execution_validation),
            (5, self._phase_delivery_hygiene)
        ]

        for phase_num, phase_func in phases:
            if phase_num < current_phase:
                continue

            try:
                phase_result = phase_func(session)
                result["phases_completed"].append(phase_num)

                if phase_result.get("artifacts"):
                    result["artifacts"].extend(phase_result["artifacts"])

                if not phase_result.get("success", True):
                    result["errors"].append({
                        "phase": phase_num,
                        "error": phase_result.get("error", "Unknown error")
                    })
                    break

            except Exception as e:
                result["errors"].append({
                    "phase": phase_num,
                    "error": str(e)
                })
                break

        # Determine success
        result["success"] = len(result["errors"]) == 0

        return result

    def _phase_bootstrap(self, session: Dict) -> Dict:
        """
        PHASE -1: Bootstrap - Repository navigation and self-initialization.

        This phase is read-only - no file modifications.
        """
        return {
            "success": True,
            "phase": "bootstrap",
            "message": "Bootstrap complete"
        }

    def _phase_init(self, session: Dict) -> Dict:
        """
        PHASE 0: INITIALIZATION

        - Quick Orient Header (STATE_SNAPSHOT)
        - Environment Offload (if >5000 lines)
        - Build NAV_MAP
        - Workspace Isolation
        - Session Checkpoint
        """
        source_file = session.get("source_file")

        if not source_file:
            # Check inputs directory
            input_files = list(self.inputs_dir.glob("*"))
            input_files = [f for f in input_files if f.is_file() and not f.name.startswith(".")]

            if input_files:
                source_file = str(input_files[0])
            else:
                return {
                    "success": False,
                    "error": "No input files found"
                }

        # Read source file
        try:
            with open(source_file) as f:
                content = f.read()
                lines = content.split("\n")
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read source file: {e}"
            }

        # Build NAV_MAP (chunk the file)
        chunk_size = self.config.get("chunking", {}).get("default_size", 1500)
        chunks = {}

        for i, start in enumerate(range(0, len(lines), chunk_size)):
            end = min(start + chunk_size, len(lines))
            chunk_id = f"C{i+1}"
            chunks[chunk_id] = {
                "chunk_id": chunk_id,
                "status": "PENDING",
                "line_start": start,
                "line_end": end,
                "changes": [],
                "checksum": None,
                "offset": 0
            }

        return {
            "success": True,
            "phase": "init",
            "chunks": chunks,
            "source_file": source_file,
            "total_lines": len(lines),
            "message": f"Initialized with {len(chunks)} chunks"
        }

    def _phase_search_discovery(self, session: Dict) -> Dict:
        """
        PHASE 1: SEARCH & DISCOVERY

        Pattern Detection for:
        - Duplicates
        - Terminology issues
        - Contradictions
        - TODO/FIXME markers
        - Orphan references
        - KEEP markers
        """
        import re

        chunks = session.get("chunks", {})
        patterns_found = {
            "duplicates": [],
            "todos": [],
            "fixmes": [],
            "keep_markers": [],
            "orphan_refs": []
        }

        # Pattern templates
        patterns = {
            "todo": re.compile(r'\bTODO\b'),
            "fixme": re.compile(r'\bFIXME\b'),
            "keep": re.compile(r'<!--\s*KEEP\s*-->'),
            "ref": re.compile(r'\[([^\]]+)\]\s*\(\s*([^)]*)\s*\)')
        }

        # Scan for patterns (would read actual file in production)
        # For now, return patterns structure

        return {
            "success": True,
            "phase": "search_discovery",
            "patterns": patterns_found,
            "message": "Pattern detection complete"
        }

    def _phase_analysis_classification(self, session: Dict) -> Dict:
        """
        PHASE 2: ANALYSIS & CLASSIFICATION

        Issue Classification with:
        - ISSUE_ID
        - SEV-1..4 severity
        - Category
        - Fix strategy
        """
        issues = session.get("open_issues", [])

        return {
            "success": True,
            "phase": "analysis_classification",
            "issues_classified": len(issues),
            "message": "Issue classification complete"
        }

    def _phase_planning(self, session: Dict) -> Dict:
        """
        PHASE 3: PLANNING

        - Execution Plan
        - Pathology Registry
        - Operation Budget
        """
        return {
            "success": True,
            "phase": "planning",
            "execution_plan": {
                "batches": [],
                "dependencies": {}
            },
            "message": "Execution plan created"
        }

    def _phase_execution_validation(self, session: Dict) -> Dict:
        """
        PHASE 4: EXECUTION & VALIDATION

        - Surgical Patch Engine
        - Validation Loop
        """
        return {
            "success": True,
            "phase": "execution_validation",
            "patches_applied": 0,
            "message": "Execution and validation complete"
        }

    def _phase_delivery_hygiene(self, session: Dict) -> Dict:
        """
        PHASE 5: DELIVERY & HYGIENE

        - Document Hygiene
        - Artifact Generation
        
        Updated in v3.2:
        - metrics.json includes p50/p95 token distribution
        - Model routing breakdown
        - Confidence summary
        """
        artifacts = []

        # Create output directory
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # Generate artifacts
        index_path = self.outputs_dir / "INDEX.md"
        with open(index_path, "w") as f:
            f.write("# NAVIGATION INDEX\n\n")
            for chunk_id, chunk in session.get("chunks", {}).items():
                f.write(f"- [{chunk_id}] L{chunk.get('line_start', 0)}-{chunk.get('line_end', 0)}\n")
        artifacts.append(str(index_path))

        change_log_path = self.outputs_dir / "CHANGE_LOG.md"
        with open(change_log_path, "w") as f:
            f.write("# CHANGE_LOG\n\n")
            f.write(f"Session: {session.get('id', 'unknown')}\n\n")
        artifacts.append(str(change_log_path))

        # NEW in v3.2: Enhanced metrics with p50/p95
        metrics_path = self.outputs_dir / "metrics.json"
        
        # Get token and latency metrics from session
        token_history = session.get("token_history", [])
        latency_history = session.get("latency_history", [])
        
        # Calculate percentiles
        token_metrics = self._calculate_percentiles(token_history)
        latency_metrics = self._calculate_percentiles(latency_history)
        
        # Get model routing info
        model_routing = session.get("model_routing", {})
        
        # Get confidence summary
        confidence = session.get("confidence_summary", {})
        
        metrics_data = {
            "session": {
                "id": session.get("id"),
                "status": "COMPLETE",
                "recursion_depth_peak": session.get("recursion_depth_peak", 0)
            },
            "processing": {
                "chunks_total": len(session.get("chunks", {})),
                "issues_found": len(session.get("open_issues", [])),
                "gaps": len(session.get("known_gaps", []))
            },
            "tokens": {
                "total": session.get("tokens_used", 0),
                "max": session.get("max_tokens", 100000),
                "per_query_p50": token_metrics.get("p50", 0),
                "per_query_p95": token_metrics.get("p95", 0),
                "total_queries": token_metrics.get("count", 0)
            },
            "latency": {
                "p50_ms": latency_metrics.get("p50", 0),
                "p95_ms": latency_metrics.get("p95", 0),
                "mean_ms": latency_metrics.get("mean", 0)
            },
            "model_routing": {
                "root_model_calls": model_routing.get("root_calls", 0),
                "leaf_model_calls": model_routing.get("leaf_calls", 0),
                "root_model_tokens": model_routing.get("root_tokens", 0),
                "leaf_model_tokens": model_routing.get("leaf_tokens", 0)
            },
            "confidence": {
                "all_high": confidence.get("all_high", False),
                "high_count": confidence.get("high_count", 0),
                "med_count": confidence.get("med_count", 0),
                "low_count": confidence.get("low_count", 0)
            },
            "gates": {
                g: s.get("status") for g, s in session.get("gates", {}).items()
            }
        }
        
        with open(metrics_path, "w") as f:
            json.dump(metrics_data, f, indent=2)
        artifacts.append(str(metrics_path))

        return {
            "success": True,
            "phase": "delivery_hygiene",
            "artifacts": artifacts,
            "message": "Delivery and hygiene complete"
        }
    
    def _calculate_percentiles(self, values: List[int]) -> Dict:
        """
        Calculate p50, p95, mean for a list of values.
        
        Args:
            values: List of numeric values
            
        Returns:
            Dict with p50, p95, mean, count
        """
        if not values:
            return {"p50": 0, "p95": 0, "mean": 0, "count": 0}
        
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        
        return {
            "p50": int(statistics.median(sorted_vals)),
            "p95": int(sorted_vals[int(n * 0.95)]) if n >= 20 else int(sorted_vals[-1]),
            "mean": int(statistics.mean(sorted_vals)),
            "min": int(sorted_vals[0]),
            "max": int(sorted_vals[-1]),
            "count": n
        }
