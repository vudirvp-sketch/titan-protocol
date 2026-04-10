"""
ContentPipeline - 6-Phase Execution Flow for TITAN Protocol.

Implements the complete pipeline flow:
    INIT → DISCOVER → ANALYZE → PLAN → EXEC → DELIVER

Each phase includes gate checks (GATE-00 through GATE-05) and emits
GapEvent via EventBus on failure.

ITEM_C002-C007: Complete pipeline implementation.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

from .phases import PipelinePhase, PhaseResult
from .config import PipelineConfig
from .errors import GateFailedError, PhaseAbortedError, RLMTerminationError
from .checkpoint import PipelineCheckpoint


class Severity(IntEnum):
    """Issue severity levels."""
    SEV_1 = 1  # Critical: blocks delivery
    SEV_2 = 2  # Major: degrades quality
    SEV_3 = 3  # Minor: cosmetic or style
    SEV_4 = 4  # Info: observation only


class ContentPipeline:
    """
    6-Phase Content Pipeline for TITAN Protocol.
    
    Pipeline Flow:
    1. INIT - State snapshot, navigation map, preflight checks (GATE-00)
    2. DISCOVER - 4-pass strategy: GREP → REGEX → AST → CHUNK (GATE-01)
    3. ANALYZE - Issue classification, ONTOLOGY binding (GATE-02)
    4. PLAN - DAG construction, budget allocation (GATE-03)
    5. EXEC - Idempotent patch application, SIGNAL_EQ verification (GATE-04)
    6. DELIVER - Hygiene strip, 7 artifacts generation (GATE-05)
    
    Usage:
        config = PipelineConfig(seed=42)
        pipeline = ContentPipeline(config)
        results = pipeline.execute({"target_files": ["src/module.py"]})
    """
    
    # Issue classification
    ISSUE_ID_PREFIX = "ISS"
    
    ONTOLOGY_MAP = {
        "stub": "INCOMPLETE_IMPLEMENTATION",
        "missing_test": "COVERAGE_GAP",
        "broken_import": "DEPENDENCY_FAILURE",
        "type_error": "TYPE_VIOLATION",
        "pattern_violation": "PATTERN_NONCONFORMANCE",
        "gap_event": "PROTOCOL_DEVIATION",
        "security": "SECURITY_VULNERABILITY",
        "performance": "PERFORMANCE_DEGRADATION",
    }
    
    PATHOLOGY_REGISTRY = {
        "INCOMPLETE_IMPLEMENTATION": {
            "canonical_fix": "Implement with full logic, no pass/.../NotImplemented",
            "sae_ref": "SAE-001",
        },
        "COVERAGE_GAP": {
            "canonical_fix": "Add unit + integration test for uncovered path",
            "sae_ref": "SAE-002",
        },
        "DEPENDENCY_FAILURE": {
            "canonical_fix": "Resolve import, add missing dependency or mock",
            "sae_ref": "SAE-003",
        },
        "TYPE_VIOLATION": {
            "canonical_fix": "Add type annotations and validate at runtime",
            "sae_ref": "SAE-004",
        },
        "PATTERN_NONCONFORMANCE": {
            "canonical_fix": "Refactor to match canonical pattern schema",
            "sae_ref": "SAE-005",
        },
    }
    
    SEVEN_ARTIFACTS = [
        "patch_manifest",
        "issue_report",
        "dependency_graph",
        "budget_report",
        "validation_report",
        "gap_event_log",
        "delivery_checksum",
    ]
    
    def __init__(self, config: PipelineConfig):
        """Initialize ContentPipeline with configuration."""
        self.config = config
        self.state: Dict[str, Any] = {}
        self._checkpoint = PipelineCheckpoint(config.checkpoint_dir)
        self._emitted_events: List[Any] = []
        
    def _get_event_bus(self):
        """Get or create EventBus singleton."""
        try:
            from src.events import EventBus
            return EventBus.get_instance() if hasattr(EventBus, 'get_instance') else EventBus()
        except ImportError:
            return None
    
    def _emit_gap_event(self, source: str, gate: str, reason: str, severity: str = "CRITICAL") -> None:
        """Emit GapEvent via EventBus.

        Creates a GapEvent for internal tracking (tests) and a proper Event
        for the EventBus (which requires event_type and EventSeverity attributes).
        """
        try:
            from src.events.gap_event import GapEvent
            from src.events.event_bus import Event, EventSeverity

            gap = GapEvent(
                source=source,
                gate=gate,
                reason=reason,
                timestamp=datetime.now(timezone.utc).isoformat(),
                severity=severity,
            )
            self._emitted_events.append(gap)

            bus = self._get_event_bus()
            if bus and hasattr(bus, 'emit'):
                severity_map = {
                    "CRITICAL": EventSeverity.CRITICAL,
                    "WARN": EventSeverity.WARN,
                    "INFO": EventSeverity.INFO,
                    "DEBUG": EventSeverity.DEBUG,
                }
                event = Event(
                    event_type="GAP_EVENT",
                    data=gap.to_dict(),
                    severity=severity_map.get(severity, EventSeverity.WARN),
                    source=source,
                )
                bus.emit(event)
        except ImportError:
            pass  # GapEvent or EventBus not available
    
    def _halt_with_gap(self, phase: str, gate: str, reason: str) -> None:
        """Halt pipeline and emit GapEvent before raising GateFailedError."""
        self._emit_gap_event(
            source=f"ContentPipeline.{phase}",
            gate=gate,
            reason=reason,
            severity="CRITICAL",
        )
        raise GateFailedError(
            message=f"Gate {gate} failed in {phase}: {reason}",
            phase=phase,
            gate=gate,
        )
    
    # =========================================================================
    # INIT Phase (ITEM_C002)
    # =========================================================================
    
    def _compute_file_checksum(self, filepath: str) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except (OSError, IOError):
            return ""
    
    def _create_state_snapshot(self) -> Dict[str, Any]:
        """Create a snapshot of current repo state with SHA-256 checksums."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "files": {},
            "config_checksums": {},
        }
        
        # Snapshot key config files
        config_paths = [
            self.config.prompt_registry_path,
            self.config.nav_map_path,
            "config/adaptation_matrix.yaml",
            "config/intent_classifier.yaml",
        ]
        for cp in config_paths:
            if os.path.exists(cp):
                snapshot["config_checksums"][cp] = self._compute_file_checksum(cp)
        
        # Snapshot source files under src/
        if os.path.isdir("src"):
            for root, _dirs, files in os.walk("src"):
                for fname in files:
                    if fname.endswith(".py"):
                        fpath = os.path.join(root, fname)
                        snapshot["files"][fpath] = self._compute_file_checksum(fpath)
        
        return snapshot
    
    def _build_navigation_map(self) -> Dict[str, Any]:
        """Build navigation map from .ai/nav_map.json."""
        nav_map_path = self.config.nav_map_path
        if not os.path.exists(nav_map_path):
            raise PhaseAbortedError(
                f"Navigation map not found at {nav_map_path}",
                phase="INIT",
            )
        with open(nav_map_path, "r", encoding="utf-8") as f:
            nav_map = json.load(f)
        
        # Validate required sections
        required_sections = ["modules", "entry_points", "routing"]
        missing = [s for s in required_sections if s not in nav_map]
        if missing:
            raise PhaseAbortedError(
                f"Navigation map missing sections: {missing}",
                phase="INIT",
            )
        return nav_map
    
    def _run_preflight_checks(self) -> bool:
        """GATE-00: Run preflight checks before pipeline execution."""
        checks = {
            "prompt_registry_exists": os.path.exists(self.config.prompt_registry_path),
            "nav_map_valid": "nav_map" in self.state,
            "config_dir_exists": os.path.isdir("config"),
            "src_dir_exists": os.path.isdir("src"),
            "event_bus_available": self._get_event_bus() is not None,
        }
        all_passed = all(checks.values())
        self.state["preflight_checks"] = checks
        return all_passed
    
    def _phase_init(self, input_context: Dict[str, Any]) -> PhaseResult:
        """INIT phase: snapshot state, build nav map, run preflight."""
        start = time.monotonic()
        self.state["input_context"] = input_context
        
        # Step 1: Create state snapshot with SHA-256 checksums
        try:
            snapshot = self._create_state_snapshot()
            self.state["snapshot"] = snapshot
        except Exception as exc:
            self._halt_with_gap("INIT", "GATE-00", f"State snapshot failed: {exc}")
        
        # Step 2: Build navigation map
        try:
            nav_map = self._build_navigation_map()
            self.state["nav_map"] = nav_map
        except PhaseAbortedError:
            self._halt_with_gap("INIT", "GATE-00", "Navigation map build failed")
        
        # Step 3: Run preflight checks (GATE-00)
        if not self._run_preflight_checks():
            failed = {
                k: v for k, v in self.state.get("preflight_checks", {}).items() if not v
            }
            self._halt_with_gap(
                "INIT", "GATE-00",
                f"Preflight checks failed: {list(failed.keys())}",
            )
        
        duration_ms = (time.monotonic() - start) * 1000
        return PhaseResult(
            phase=PipelinePhase.INIT,
            success=True,
            artifacts={"snapshot": self.state.get("snapshot", {})},
            checksum=hashlib.sha256(
                json.dumps(self.state.get("snapshot", {}), sort_keys=True, default=str).encode()
            ).hexdigest(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_passed=True,
            duration_ms=duration_ms,
        )
    
    # =========================================================================
    # DISCOVER Phase (ITEM_C003)
    # =========================================================================
    
    def _detect_encoding(self, filepath: str) -> str:
        """Detect file encoding using chardet."""
        try:
            import chardet
            with open(filepath, "rb") as f:
                raw = f.read(65536)  # Read first 64KB for detection
            result = chardet.detect(raw)
            return result.get("encoding", "utf-8") or "utf-8"
        except ImportError:
            return "utf-8"
        except (OSError, IOError):
            return "utf-8"
    
    def _pass_grep(self, file_list: List[str]) -> List[Dict[str, Any]]:
        """Pass 1: GREP — fast line-level pattern matching."""
        patterns = [
            r"def\s+\w+",
            r"class\s+\w+",
            r"import\s+\w+",
            r"from\s+[\w.]+\s+import",
            r"TODO|FIXME|HACK|XXX",
        ]
        chunks = []
        for fpath in file_list:
            if not os.path.exists(fpath):
                continue
            encoding = self._detect_encoding(fpath)
            try:
                with open(fpath, "r", encoding=encoding) as f:
                    for lineno, line in enumerate(f, 1):
                        for pat in patterns:
                            if re.search(pat, line):
                                chunks.append({
                                    "file": fpath,
                                    "line": lineno,
                                    "content": line.strip(),
                                    "match_type": "GREP",
                                    "pattern": pat,
                                })
            except (UnicodeDecodeError, OSError):
                continue
        return chunks
    
    def _pass_regex(self, file_list: List[str]) -> List[Dict[str, Any]]:
        """Pass 2: REGEX — structural pattern extraction."""
        structural_patterns = [
            (r"def\s+(\w+)\s*\(([^)]*)\)", "function_def"),
            (r"class\s+(\w+)(?:\(([^)]*)\))?", "class_def"),
            (r"(\w+)\s*=\s*(.+)", "assignment"),
            (r"@\w+", "decorator"),
        ]
        chunks = []
        for fpath in file_list:
            if not os.path.exists(fpath):
                continue
            encoding = self._detect_encoding(fpath)
            try:
                with open(fpath, "r", encoding=encoding) as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for pat, match_type in structural_patterns:
                for m in re.finditer(pat, content):
                    chunks.append({
                        "file": fpath,
                        "span": m.span(),
                        "groups": m.groups(),
                        "match_type": "REGEX",
                        "category": match_type,
                    })
        return chunks
    
    def _pass_ast(self, file_list: List[str]) -> List[Dict[str, Any]]:
        """Pass 3: AST — deep structural analysis of Python files."""
        chunks = []
        for fpath in file_list:
            if not fpath.endswith(".py") or not os.path.exists(fpath):
                continue
            encoding = self._detect_encoding(fpath)
            try:
                with open(fpath, "r", encoding=encoding) as f:
                    content = f.read()
                tree = ast.parse(content, filename=fpath)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    chunks.append({
                        "file": fpath,
                        "type": "function",
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "args": [a.arg for a in node.args.args],
                        "decorators": [
                            d.id if isinstance(d, ast.Name) else str(d)
                            for d in node.decorator_list
                        ],
                        "match_type": "AST",
                    })
                elif isinstance(node, ast.ClassDef):
                    chunks.append({
                        "file": fpath,
                        "type": "class",
                        "name": node.name,
                        "line": node.lineno,
                        "bases": [
                            b.id if isinstance(b, ast.Name) else str(b)
                            for b in node.bases
                        ],
                        "match_type": "AST",
                    })
        return chunks
    
    def _pass_chunk(self, file_list: List[str]) -> List[Dict[str, Any]]:
        """Pass 4: CHUNK — split files into semantic chunks."""
        chunks = []
        chunk_size = 50  # lines per chunk
        for fpath in file_list:
            if not os.path.exists(fpath):
                continue
            encoding = self._detect_encoding(fpath)
            try:
                with open(fpath, "r", encoding=encoding) as f:
                    lines = f.readlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i in range(0, len(lines), chunk_size):
                chunk_lines = lines[i : i + chunk_size]
                chunks.append({
                    "file": fpath,
                    "start_line": i + 1,
                    "end_line": min(i + chunk_size, len(lines)),
                    "content": "".join(chunk_lines),
                    "line_count": len(chunk_lines),
                    "match_type": "CHUNK",
                })
        return chunks
    
    def _build_dependency_graph(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build dependency graph from discovered chunks."""
        graph: Dict[str, Any] = {"nodes": [], "edges": []}
        # Nodes: each unique file
        files = set(c.get("file", "") for c in chunks if c.get("file"))
        for f in files:
            graph["nodes"].append({"id": f, "type": "file"})
        # Edges: import-based dependencies
        for c in chunks:
            if c.get("match_type") == "GREP" and "import" in c.get("pattern", ""):
                source = c.get("file", "")
                content = c.get("content", "")
                # Extract imported module
                imp_match = re.match(r"(?:from|import)\s+([\w.]+)", content)
                if imp_match and source:
                    graph["edges"].append({
                        "source": source,
                        "target": imp_match.group(1),
                        "type": "import",
                    })
        return graph
    
    def _phase_discover(self, input_context: Dict[str, Any]) -> PhaseResult:
        """DISCOVER phase: 4-pass strategy to find relevant content."""
        start = time.monotonic()
        nav_map = self.state.get("nav_map", {})
        target_files = input_context.get("target_files", [])
        
        # If no target files specified, derive from nav_map
        if not target_files:
            modules = nav_map.get("modules", {})
            target_files = [
                os.path.join("src", m, f)
                for m, files in modules.items()
                for f in (files if isinstance(files, list) else [])
                if f.endswith(".py")
            ]
        
        # Filter to existing files
        target_files = [f for f in target_files if os.path.exists(f)]
        
        # 4-pass discovery strategy
        grep_chunks = self._pass_grep(target_files)
        regex_chunks = self._pass_regex(target_files)
        ast_chunks = self._pass_ast(target_files)
        chunk_chunks = self._pass_chunk(target_files)
        
        all_chunks = grep_chunks + regex_chunks + ast_chunks + chunk_chunks
        self.state["discovered_chunks"] = all_chunks
        self.state["discovery_stats"] = {
            "total_files": len(target_files),
            "grep_chunks": len(grep_chunks),
            "regex_chunks": len(regex_chunks),
            "ast_chunks": len(ast_chunks),
            "chunk_chunks": len(chunk_chunks),
            "total_chunks": len(all_chunks),
        }
        
        # Build dependency graph
        dep_graph = self._build_dependency_graph(all_chunks)
        self.state["dependency_graph"] = dep_graph
        
        # GATE-01: Validate discovery results
        if len(all_chunks) == 0:
            self._halt_with_gap(
                "DISCOVER", "GATE-01",
                "No chunks discovered from any pass",
            )
        
        duration_ms = (time.monotonic() - start) * 1000
        return PhaseResult(
            phase=PipelinePhase.DISCOVER,
            success=True,
            artifacts={
                "chunks": all_chunks,
                "dependency_graph": dep_graph,
                "stats": self.state["discovery_stats"],
            },
            checksum=hashlib.sha256(
                json.dumps(self.state["discovery_stats"], sort_keys=True).encode()
            ).hexdigest(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_passed=True,
            duration_ms=duration_ms,
        )
    
    # =========================================================================
    # ANALYZE Phase (ITEM_C004)
    # =========================================================================
    
    def _classify_issue(self, chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Classify a discovered chunk into an issue with ID and severity."""
        content = chunk.get("content", "")
        match_type = chunk.get("match_type", "")
        
        # Detection rules
        if any(kw in content for kw in ["pass", "...", "NotImplemented"]):
            return {
                "issue_id": f"{self.ISSUE_ID_PREFIX}-{chunk.get('file','')}:{chunk.get('line',0)}",
                "severity": Severity.SEV_1,
                "category": "stub",
                "ontology": self.ONTOLOGY_MAP["stub"],
                "chunk_ref": chunk,
            }
        if "TODO" in content or "FIXME" in content:
            return {
                "issue_id": f"{self.ISSUE_ID_PREFIX}-{chunk.get('file','')}:{chunk.get('line',0)}",
                "severity": Severity.SEV_2,
                "category": "incomplete",
                "ontology": "INCOMPLETE_IMPLEMENTATION",
                "chunk_ref": chunk,
            }
        if match_type == "REGEX" and chunk.get("category") == "function_def":
            groups = chunk.get("groups", ("", ""))
            args = groups[1] if len(groups) > 1 else ""
            if args and not args.strip():
                return {
                    "issue_id": f"{self.ISSUE_ID_PREFIX}-{chunk.get('file','')}:sig",
                    "severity": Severity.SEV_4,
                    "category": "no_args",
                    "ontology": "TYPE_VIOLATION",
                    "chunk_ref": chunk,
                }
        return None
    
    def _bind_ontology(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bind each issue to ONTOLOGY terms and pathology registry."""
        for issue in issues:
            ontology_key = issue.get("ontology", "")
            pathology = self.PATHOLOGY_REGISTRY.get(ontology_key, {
                "canonical_fix": "Manual review required",
                "sae_ref": "SAE-000",
            })
            issue["pathology"] = pathology
            issue["ontology_binding"] = {
                "term": ontology_key,
                "sae_ref": pathology["sae_ref"],
                "canonical_fix": pathology["canonical_fix"],
            }
        return issues
    
    def _phase_analyze(self, input_context: Dict[str, Any]) -> PhaseResult:
        """ANALYZE phase: classify issues, bind ontology, lookup pathologies."""
        start = time.monotonic()
        chunks = self.state.get("discovered_chunks", [])
        
        # Step 1: Classify issues from discovered chunks
        issues = []
        for chunk in chunks:
            issue = self._classify_issue(chunk)
            if issue is not None:
                issues.append(issue)
        
        # Step 2: ONTOLOGY binding
        issues = self._bind_ontology(issues)
        
        # Step 3: Pathology registry lookup (already done in _bind_ontology)
        self.state["issues"] = issues
        self.state["issue_stats"] = {
            "total_issues": len(issues),
            "by_severity": {
                f"SEV_{s.value}": len([i for i in issues if i.get("severity") == s])
                for s in Severity
            },
            "by_ontology": {},
        }
        for issue in issues:
            ont = issue.get("ontology", "UNKNOWN")
            self.state["issue_stats"]["by_ontology"][ont] = (
                self.state["issue_stats"]["by_ontology"].get(ont, 0) + 1
            )
        
        # GATE-02: Validate analysis results
        if len(issues) == 0:
            # No issues found is acceptable — but emit info-level gap
            self._emit_gap_event(
                source="ContentPipeline.ANALYZE",
                gate="GATE-02",
                reason="No issues classified — verify discovery completeness",
                severity="INFO",
            )
        
        # If SEV-1 issues exceed threshold, that is a hard gate failure
        sev1_count = self.state["issue_stats"]["by_severity"].get("SEV_1", 0)
        if sev1_count > 50:
            self._halt_with_gap(
                "ANALYZE", "GATE-02",
                f"Too many SEV-1 issues ({sev1_count}), threshold is 50",
            )
        
        duration_ms = (time.monotonic() - start) * 1000
        return PhaseResult(
            phase=PipelinePhase.ANALYZE,
            success=True,
            artifacts={
                "issues": issues,
                "stats": self.state["issue_stats"],
            },
            checksum=hashlib.sha256(
                json.dumps(self.state["issue_stats"], sort_keys=True, default=str).encode()
            ).hexdigest(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_passed=True,
            duration_ms=duration_ms,
        )
    
    # =========================================================================
    # PLAN Phase (ITEM_C005)
    # =========================================================================
    
    def _construct_dag(self, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Construct a DAG of remediation actions from issues."""
        dag: Dict[str, Any] = {"nodes": [], "edges": []}
        severity_order = {Severity.SEV_1: 0, Severity.SEV_2: 1, Severity.SEV_3: 2, Severity.SEV_4: 3}
        
        # Sort issues by severity (critical first)
        sorted_issues = sorted(issues, key=lambda i: severity_order.get(i.get("severity", Severity.SEV_4), 99))
        
        # Create nodes
        for idx, issue in enumerate(sorted_issues):
            sev = issue.get("severity", Severity.SEV_4)
            dag["nodes"].append({
                "id": f"action_{idx}",
                "issue_id": issue.get("issue_id", ""),
                "severity": int(sev) if isinstance(sev, Severity) else sev,
                "ontology": issue.get("ontology", ""),
                "canonical_fix": issue.get("pathology", {}).get("canonical_fix", ""),
                "parallel_safe": sev >= Severity.SEV_3 if isinstance(sev, Severity) else sev >= 3,
            })
        
        # Create edges based on file dependencies
        for i, node_a in enumerate(dag["nodes"]):
            for j, node_b in enumerate(dag["nodes"]):
                if i >= j:
                    continue
                issue_a = sorted_issues[i]
                issue_b = sorted_issues[j]
                # Same file → sequential dependency
                if issue_a.get("chunk_ref", {}).get("file") == issue_b.get("chunk_ref", {}).get("file"):
                    dag["edges"].append({
                        "from": node_a["id"],
                        "to": node_b["id"],
                        "type": "sequential",
                    })
        return dag
    
    def _allocate_budget(self, dag: Dict[str, Any]) -> Dict[str, Any]:
        """Allocate token budget across DAG nodes."""
        total_tokens = self.config.budget_tokens
        nodes = dag.get("nodes", [])
        if not nodes:
            return {"total": total_tokens, "per_node": {}, "reserved": 0}
        
        # SEV-1 gets 40%, SEV-2 gets 30%, SEV-3 gets 20%, SEV-4 gets 10%
        severity_weights = {1: 0.4, 2: 0.3, 3: 0.2, 4: 0.1}
        total_weight = sum(severity_weights.get(n.get("severity", 4), 0.1) for n in nodes)
        per_node = {}
        for node in nodes:
            weight = severity_weights.get(node.get("severity", 4), 0.1)
            allocation = int(total_tokens * weight / total_weight) if total_weight > 0 else 0
            per_node[node["id"]] = {
                "tokens_allocated": allocation,
                "tokens_used": 0,
                "weight": weight,
            }
        
        reserved = int(total_tokens * 0.1)  # 10% reserve
        return {"total": total_tokens, "per_node": per_node, "reserved": reserved}
    
    def _calculate_consensus_weights(self, dag: Dict[str, Any]) -> Dict[str, float]:
        """Calculate consensus weights for parallel-safe actions."""
        weights = {}
        for node in dag.get("nodes", []):
            if node.get("parallel_safe", False):
                # Parallel-safe actions get equal weight
                weights[node["id"]] = 1.0
            else:
                # Sequential actions get higher weight (must complete first)
                weights[node["id"]] = 2.0
        return weights
    
    def _detect_cycle(self, dag: Dict[str, Any]) -> bool:
        """Detect cycles in the DAG."""
        visited = set()
        has_cycle = False
        
        def _detect_cycle_recursive(node_id: str, path: set) -> None:
            nonlocal has_cycle
            if node_id in path:
                has_cycle = True
                return
            if node_id in visited:
                return
            visited.add(node_id)
            path.add(node_id)
            for edge in dag.get("edges", []):
                if edge.get("from") == node_id:
                    _detect_cycle_recursive(edge.get("to", ""), path.copy())
        
        for node in dag.get("nodes", []):
            if node["id"] not in visited:
                _detect_cycle_recursive(node["id"], set())
        
        return has_cycle
    
    def _phase_plan(self, input_context: Dict[str, Any]) -> PhaseResult:
        """PLAN phase: construct DAG, allocate budget, validate plan."""
        start = time.monotonic()
        issues = self.state.get("issues", [])
        
        # Step 1: DAG construction with dependency resolution
        dag = self._construct_dag(issues)
        self.state["plan_dag"] = dag
        
        # Step 2: Budget allocation with token tracking
        budget = self._allocate_budget(dag)
        self.state["plan_budget"] = budget
        
        # Step 3: Consensus weight calculation
        consensus = self._calculate_consensus_weights(dag)
        self.state["plan_consensus"] = consensus
        
        # Step 4: Identify parallel-safe actions
        parallel_safe = [n["id"] for n in dag.get("nodes", []) if n.get("parallel_safe", False)]
        self.state["plan_parallel_safe"] = parallel_safe
        
        # GATE-03: Validate plan
        if len(dag.get("nodes", [])) == 0 and len(issues) > 0:
            self._halt_with_gap(
                "PLAN", "GATE-03",
                "Issues exist but DAG has no nodes — dependency resolution failed",
            )
        if budget.get("total", 0) <= 0:
            self._halt_with_gap(
                "PLAN", "GATE-03",
                "Budget allocation resulted in zero tokens",
            )
        
        # Check for cycles in DAG
        if self._detect_cycle(dag):
            self._halt_with_gap(
                "PLAN", "GATE-03",
                "DAG contains cycles — dependency resolution invalid",
            )
        
        duration_ms = (time.monotonic() - start) * 1000
        return PhaseResult(
            phase=PipelinePhase.PLAN,
            success=True,
            artifacts={
                "dag": dag,
                "budget": budget,
                "consensus_weights": consensus,
                "parallel_safe_actions": parallel_safe,
            },
            checksum=hashlib.sha256(
                json.dumps({"nodes": len(dag.get("nodes", [])), "edges": len(dag.get("edges", []))}, sort_keys=True).encode()
            ).hexdigest(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_passed=True,
            duration_ms=duration_ms,
        )
    
    # =========================================================================
    # EXEC Phase (ITEM_C006)
    # =========================================================================
    
    def _apply_patch_idempotent(self, file_path: str, patch: Dict[str, Any]) -> bool:
        """Apply a patch idempotently — re-application has no side effects."""
        if not os.path.exists(file_path):
            return False
        
        # Backup before patching
        backup_path = file_path + ".bak"
        if not os.path.exists(backup_path):
            try:
                shutil.copy2(file_path, backup_path)
            except OSError:
                pass
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original = f.read()
        except (OSError, UnicodeDecodeError):
            return False
        
        # Check if patch is already applied
        patch_marker = patch.get("marker", "")
        if patch_marker and patch_marker in original:
            # Patch already applied — idempotent, return success
            return True
        
        # Apply patch
        action = patch.get("action", "replace")
        patched = original
        
        if action == "replace":
            search = patch.get("search", "")
            replace = patch.get("replace", "")
            if search and search in original:
                patched = original.replace(search, replace, 1)
            else:
                return False
        elif action == "insert_after":
            anchor = patch.get("anchor", "")
            insert_text = patch.get("insert", "")
            if anchor and anchor in original:
                patched = original.replace(anchor, anchor + "\n" + insert_text, 1)
            else:
                return False
        elif action == "insert_before":
            anchor = patch.get("anchor", "")
            insert_text = patch.get("insert", "")
            if anchor and anchor in original:
                patched = original.replace(anchor, insert_text + "\n" + anchor, 1)
            else:
                return False
        else:
            return False
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(patched)
            return True
        except OSError:
            return False
    
    def _validate_patch(self, file_path: str, patch: Dict[str, Any]) -> bool:
        """Validate that a patch was applied correctly."""
        if not os.path.exists(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            return False
        marker = patch.get("marker", patch.get("replace", ""))
        return marker in content if marker else True
    
    def _verify_signal_eq(self, pre_state: Dict[str, Any], post_state: Dict[str, Any]) -> bool:
        """SIGNAL_EQ: verify that output signals match expected patterns."""
        # Compare pre/post state checksums for non-target files
        pre_files = pre_state.get("files", {})
        post_files = post_state.get("files", {})
        target_files = set(self.state.get("input_context", {}).get("target_files", []))
        
        for fpath, checksum in pre_files.items():
            if fpath in target_files:
                continue  # Target files are expected to change
            if fpath in post_files and post_files[fpath] != checksum:
                return False  # Non-target file was modified — SIGNAL_EQ violation
        return True
    
    def _phase_exec(self, input_context: Dict[str, Any]) -> PhaseResult:
        """EXEC phase: apply patches with validation, enforce PAT-24."""
        start = time.monotonic()
        dag = self.state.get("plan_dag", {})
        nodes = dag.get("nodes", [])
        
        # Capture pre-exec state for SIGNAL_EQ
        pre_exec_state = self._create_state_snapshot()
        
        applied_patches = []
        failed_patches = []
        validation_pass = 0
        max_passes = self.config.max_validation_passes  # PAT-24: max 2
        
        for node in nodes:
            patch = {
                "action": "replace",
                "search": node.get("canonical_fix", ""),
                "replace": node.get("ontology", ""),
                "marker": f"# PATCHED:{node['id']}",
            }
            success = False
            for attempt in range(max_passes):
                validation_pass = attempt + 1
                try:
                    file_path = node.get("issue_id", "").split(":")[0].replace("ISS-", "")
                    if file_path and os.path.exists(file_path):
                        applied = self._apply_patch_idempotent(file_path, patch)
                        if applied:
                            validated = self._validate_patch(file_path, patch)
                            if validated:
                                applied_patches.append({
                                    "node_id": node["id"],
                                    "file": file_path,
                                    "validation_pass": validation_pass,
                                })
                                success = True
                                break
                except Exception:
                    continue
            
            if not success:
                failed_patches.append({
                    "node_id": node["id"],
                    "attempts": validation_pass,
                })
        
        # Post-exec state for SIGNAL_EQ
        post_exec_state = self._create_state_snapshot()
        signal_eq_ok = self._verify_signal_eq(pre_exec_state, post_exec_state)
        
        self.state["exec_results"] = {
            "applied": applied_patches,
            "failed": failed_patches,
            "signal_eq": signal_eq_ok,
            "validation_passes_used": validation_pass,
        }
        
        # RLM termination check: if too many failures, terminate
        if len(nodes) > 0 and len(failed_patches) > len(nodes) * 0.5:
            self._emit_gap_event(
                source="ContentPipeline.EXEC",
                gate="GATE-04",
                reason=f"RLM termination: {len(failed_patches)}/{len(nodes)} patches failed",
                severity="CRITICAL",
            )
            raise RLMTerminationError(
                f"Over 50% of patches failed ({len(failed_patches)}/{len(nodes)})",
                phase="EXEC",
                reason="excessive_failures",
            )
        
        # GATE-04: Validate execution
        if not signal_eq_ok:
            self._halt_with_gap(
                "EXEC", "GATE-04",
                "SIGNAL_EQ verification failed — non-target files modified",
            )
        
        duration_ms = (time.monotonic() - start) * 1000
        return PhaseResult(
            phase=PipelinePhase.EXEC,
            success=True,
            artifacts={
                "applied_patches": applied_patches,
                "failed_patches": failed_patches,
                "signal_eq": signal_eq_ok,
            },
            checksum=hashlib.sha256(
                json.dumps(self.state["exec_results"], sort_keys=True, default=str).encode()
            ).hexdigest(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_passed=True,
            duration_ms=duration_ms,
        )
    
    # =========================================================================
    # DELIVER Phase (ITEM_C007)
    # =========================================================================
    
    def _apply_hygiene_strip(self, content: str) -> str:
        """Strip debug/meta/TODO annotations from content."""
        result = content
        for pattern in self.config.hygiene_strip_patterns:
            result = re.sub(pattern, "", result, flags=re.MULTILINE)
        # Remove excessive blank lines
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()
    
    def _generate_artifacts(self) -> Dict[str, Any]:
        """Generate the 7 standard delivery artifacts."""
        artifacts: Dict[str, Any] = {}
        
        # 1. patch_manifest
        artifacts["patch_manifest"] = {
            "version": "1.0",
            "patches": self.state.get("exec_results", {}).get("applied", []),
            "failed": self.state.get("exec_results", {}).get("failed", []),
            "total": len(self.state.get("plan_dag", {}).get("nodes", [])),
        }
        
        # 2. issue_report
        artifacts["issue_report"] = {
            "version": "1.0",
            "issues": self.state.get("issues", []),
            "stats": self.state.get("issue_stats", {}),
        }
        
        # 3. dependency_graph
        artifacts["dependency_graph"] = {
            "version": "1.0",
            "graph": self.state.get("dependency_graph", {}),
        }
        
        # 4. budget_report
        artifacts["budget_report"] = {
            "version": "1.0",
            "allocation": self.state.get("plan_budget", {}),
            "consensus_weights": self.state.get("plan_consensus", {}),
        }
        
        # 5. validation_report
        artifacts["validation_report"] = {
            "version": "1.0",
            "signal_eq": self.state.get("exec_results", {}).get("signal_eq", False),
            "validation_passes": self.state.get("exec_results", {}).get("validation_passes_used", 0),
            "gate_results": {
                "GATE-00": self.state.get("preflight_checks", {}),
                "GATE-01": len(self.state.get("discovered_chunks", [])) > 0,
                "GATE-02": True,  # Reached DELIVER implies ANALYZE passed
                "GATE-03": len(self.state.get("plan_dag", {}).get("nodes", [])) > 0,
                "GATE-04": self.state.get("exec_results", {}).get("signal_eq", False),
            },
        }
        
        # 6. gap_event_log
        artifacts["gap_event_log"] = {
            "version": "1.0",
            "events": [e.to_json() if hasattr(e, 'to_json') else str(e) for e in self._emitted_events],
        }
        
        # 7. delivery_checksum
        all_checksums = {}
        for name, art in artifacts.items():
            art_str = json.dumps(art, sort_keys=True, default=str)
            all_checksums[name] = hashlib.sha256(art_str.encode()).hexdigest()
        artifacts["delivery_checksum"] = {
            "version": "1.0",
            "sha256_checksums": all_checksums,
            "full_merge_checksum": hashlib.sha256(
                json.dumps(all_checksums, sort_keys=True).encode()
            ).hexdigest(),
        }
        
        return artifacts
    
    def _write_artifacts_to_disk(self, artifacts: Dict[str, Any]) -> None:
        """Write artifacts to output directory."""
        output_dir = self.config.artifact_output_dir
        os.makedirs(output_dir, exist_ok=True)
        for name, content in artifacts.items():
            filepath = os.path.join(output_dir, f"{name}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, sort_keys=True, default=str)
    
    def _phase_deliver(self, input_context: Dict[str, Any]) -> PhaseResult:
        """DELIVER phase: hygiene, artifacts, gap emission, FULL_MERGE."""
        start = time.monotonic()
        
        # Step 1: Hygiene strip on all modified files
        target_files = input_context.get("target_files", [])
        for fpath in target_files:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    cleaned = self._apply_hygiene_strip(content)
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(cleaned)
                except (OSError, UnicodeDecodeError):
                    continue
        
        # Step 2: Generate 7 artifacts
        artifacts = self._generate_artifacts()
        
        # Step 3: Emit all pending GapEvents as JSON
        audit_path = os.path.join(self.config.artifact_output_dir, "gap_events.jsonl")
        os.makedirs(self.config.artifact_output_dir, exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            for event in self._emitted_events:
                if hasattr(event, "to_json"):
                    f.write(event.to_json() + "\n")
        
        # Step 4: Write artifacts to disk
        self._write_artifacts_to_disk(artifacts)
        
        # Step 5: FULL_MERGE with SHA-256 verification
        full_merge_checksum = artifacts["delivery_checksum"]["full_merge_checksum"]
        self.state["delivery"] = {
            "artifacts": list(artifacts.keys()),
            "full_merge_checksum": full_merge_checksum,
            "hygiene_applied": True,
        }
        
        # GATE-05: Validate delivery
        expected_artifacts = set(self.SEVEN_ARTIFACTS)
        actual_artifacts = set(artifacts.keys())
        missing = expected_artifacts - actual_artifacts
        if missing:
            self._halt_with_gap(
                "DELIVER", "GATE-05",
                f"Missing artifacts: {missing}",
            )
        
        duration_ms = (time.monotonic() - start) * 1000
        return PhaseResult(
            phase=PipelinePhase.DELIVER,
            success=True,
            artifacts=artifacts,
            checksum=full_merge_checksum,
            timestamp=datetime.now(timezone.utc).isoformat(),
            gate_passed=True,
            duration_ms=duration_ms,
        )
    
    # =========================================================================
    # Main Execution Entry Point
    # =========================================================================
    
    def execute(self, input_context: Dict[str, Any]) -> Dict[str, PhaseResult]:
        """
        Execute the full 6-phase ContentPipeline.
        
        Args:
            input_context: Dictionary containing:
                - target_files: List of files to process
                - intent: Dictionary with pattern_id, text, etc.
        
        Returns:
            Dictionary mapping phase names to PhaseResult objects
        """
        phase_map = {
            "INIT": self._phase_init,
            "DISCOVER": self._phase_discover,
            "ANALYZE": self._phase_analyze,
            "PLAN": self._phase_plan,
            "EXEC": self._phase_exec,
            "DELIVER": self._phase_deliver,
        }
        
        # Check for resumption
        latest = self._checkpoint.get_latest_phase()
        if latest and latest in phase_map:
            saved = self._checkpoint.load(latest)
            if saved:
                self.state = saved.get("state", self.state)
        
        phase_order = ["INIT", "DISCOVER", "ANALYZE", "PLAN", "EXEC", "DELIVER"]
        start_idx = phase_order.index(latest) + 1 if latest else 0
        results: Dict[str, PhaseResult] = {}
        
        for phase_name in phase_order[start_idx:]:
            phase_fn = phase_map[phase_name]
            result = phase_fn(input_context)
            results[phase_name] = result
            if result.success:
                self._checkpoint.save(phase_name, self.state)
            else:
                break
        
        return results
    
    def get_emitted_events(self) -> List[Any]:
        """Get all emitted GapEvents for testing/validation."""
        return self._emitted_events
    
    def clear_events(self) -> None:
        """Clear all emitted events."""
        self._emitted_events.clear()
