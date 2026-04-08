#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Unified CLI Interface
Version: 3.2.3

A harness-first CLI that positions TITAN as an execution layer,
not just a set of prompts. Provides deterministic JSON output
and explicit entry points for all operations.
"""

import argparse
import json
import sys
import os
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import jsonschema
from jsonschema import validate, ValidationError as JsonSchemaError

from state.state_manager import StateManager, InputSizeValidator, CredentialManager
from harness.orchestrator import Orchestrator
from events.event_bus import EventBus


class OutputFormat(Enum):
    JSON = "json"
    TEXT = "text"
    MARKDOWN = "markdown"


class ExecutionMode(Enum):
    INTERACTIVE = "interactive"
    BATCH = "batch"
    AGENT_RUN = "agent-run"


# =============================================================================
# T1: Config Schema Validation
# =============================================================================

def validate_config(config_path: str, schema_path: str = None) -> Dict:
    """
    Validate config against JSON schema.
    
    Args:
        config_path: Path to config.yaml
        schema_path: Path to config.schema.json (auto-detected if not provided)
    
    Returns:
        Validated config dictionary
    
    Raises:
        ValueError: If validation fails
    """
    config_path = Path(config_path)
    
    # Auto-detect schema path
    if schema_path is None:
        schema_path = config_path.parent / "schemas" / "config.schema.json"
    else:
        schema_path = Path(schema_path)
    
    # Load config
    if not config_path.exists():
        raise ValueError(f"[gap: config_not_found] {config_path}")
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Load schema
    if not schema_path.exists():
        # Schema validation is optional if schema file missing
        return config
    
    with open(schema_path) as f:
        schema = json.load(f)
    
    # Validate
    try:
        validate(instance=config, schema=schema)
    except JsonSchemaError as e:
        raise ValueError(f"[gap: config_validation_failed] {e.message}")
    
    return config


def validate_config_safe(config_path: str) -> Dict:
    """
    Validate config with graceful error handling.
    
    Returns:
        Tuple of (config, errors)
    """
    errors = []
    config = {}
    
    try:
        config = validate_config(config_path)
    except ValueError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(f"[gap: config_load_error] {str(e)}")
    
    return config, errors


class TitanCLI:
    """
    Unified CLI interface for TITAN FUSE Protocol.

    Commands:
        init      - Initialize a new TITAN session
        validate  - Run validation gates (GATE-00 through GATE-05)
        resume    - Resume from checkpoint
        login     - Authenticate with LLM provider
        doctor    - Health check and diagnostics
        process   - Process input files through the pipeline
        status    - Show current session status
        compact   - Trigger context compaction
        export    - Export session artifacts
    """

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or Path.cwd()
        self.config_path = self.repo_root / "config.yaml"
        
        # T1: Load and validate config
        self.config, self.config_errors = validate_config_safe(str(self.config_path))
        
        # T2: Initialize InputSizeValidator with config limits
        security_config = self.config.get("security", {})
        self.input_validator = InputSizeValidator(
            max_file_size=security_config.get("max_input_file_size_mb", 100) * 1024 * 1024,
            max_total_size=security_config.get("max_total_input_size_mb", 500) * 1024 * 1024
        )
        
        # T4: Initialize CredentialManager
        self.credential_manager = CredentialManager()
        
        self.state_manager = StateManager(self.repo_root)
        self.orchestrator = Orchestrator(self.repo_root)
        self.event_bus = EventBus()

        self.output_format = OutputFormat.JSON
        self.execution_mode = ExecutionMode.INTERACTIVE
        self.verbose = False

    def set_output_format(self, fmt: str) -> None:
        """Set output format for all commands."""
        self.output_format = OutputFormat(fmt)

    def set_execution_mode(self, mode: str) -> None:
        """Set execution mode."""
        self.execution_mode = ExecutionMode(mode)

    def _output(self, data: Dict[str, Any], success: bool = True) -> int:
        """
        Format and output result based on output_format setting.
        Returns exit code (0 for success, non-zero for failure).
        """
        result = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "success": success,
            "mode": self.execution_mode.value,
            **data
        }

        if self.output_format == OutputFormat.JSON:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif self.output_format == OutputFormat.MARKDOWN:
            self._output_markdown(result)
        else:
            self._output_text(result)

        return 0 if success else 1

    def _output_text(self, data: Dict[str, Any]) -> None:
        """Human-readable text output."""
        status = "✓" if data.get("success") else "✗"
        print(f"[{status}] {data.get('command', 'unknown')}")

        for key, value in data.items():
            if key not in ("timestamp", "success", "mode", "command"):
                if isinstance(value, dict):
                    print(f"  {key}:")
                    for k, v in value.items():
                        print(f"    {k}: {v}")
                elif isinstance(value, list):
                    print(f"  {key}: {', '.join(map(str, value))}")
                else:
                    print(f"  {key}: {value}")

    def _output_markdown(self, data: Dict[str, Any]) -> None:
        """Markdown-formatted output."""
        status = "✅" if data.get("success") else "❌"
        print(f"## {status} {data.get('command', 'unknown').upper()}\n")
        print(f"**Timestamp:** {data['timestamp']}\n")
        print(f"**Mode:** {data['mode']}\n")

        for key, value in data.items():
            if key not in ("timestamp", "success", "mode", "command"):
                if isinstance(value, dict):
                    print(f"### {key}\n")
                    for k, v in value.items():
                        print(f"- **{k}:** {v}")
                    print()
                elif isinstance(value, list):
                    print(f"### {key}\n")
                    for item in value:
                        print(f"- {item}")
                    print()
                else:
                    print(f"**{key}:** {value}\n")

    # =========================================================================
    # CLI COMMANDS
    # =========================================================================

    def cmd_init(self, session_id: Optional[str] = None,
                 input_files: Optional[list] = None,
                 max_tokens: int = 100000) -> int:
        """
        Initialize a new TITAN session.

        Args:
            session_id: Optional session identifier (auto-generated if not provided)
            input_files: List of input file paths to process
            max_tokens: Maximum tokens for the session

        Returns:
            Exit code (0 for success)
        """
        # T2: Validate input file sizes before processing
        if input_files:
            validation = self.input_validator.validate(input_files)
            if not validation["valid"]:
                return self._output({
                    "command": "init",
                    "error": "[gap: input_validation_failed]",
                    "validation_errors": validation["errors"]
                }, success=False)
        
        # Initialize state
        session = self.state_manager.create_session(
            session_id=session_id,
            max_tokens=max_tokens,
            input_files=input_files or []
        )

        # T4: Validate no credentials leaked into state
        if not self.credential_manager.validate_no_key_in_state(session):
            return self._output({
                "command": "init",
                "error": "[gap: credential_leak_detected] Session state contains credential-like values"
            }, success=False)

        # Emit initialization event
        self.event_bus.emit_simple("session.init", {
            "session_id": session["id"],
            "max_tokens": max_tokens,
            "input_count": len(input_files or [])
        })

        return self._output({
            "command": "init",
            "session": {
                "id": session["id"],
                "status": "INITIALIZED",
                "max_tokens": max_tokens,
                "created_at": session["created_at"]
            },
            "input_files": input_files or [],
            "config_validation": {
                "errors": self.config_errors,
                "valid": len(self.config_errors) == 0
            },
            "next_steps": [
                "Run 'titan validate' to check GATE-00",
                "Run 'titan process' to start processing",
                "Run 'titan status' to check session state"
            ]
        })

    def cmd_validate(self, gate: Optional[str] = None,
                     all_gates: bool = False) -> int:
        """
        Run validation gates.

        Args:
            gate: Specific gate to validate (GATE-00 through GATE-05)
            all_gates: Run all gates in sequence

        Returns:
            Exit code (0 if all gates pass)
        """
        session = self.state_manager.get_current_session()
        if not session:
            return self._output({
                "command": "validate",
                "error": "No active session. Run 'titan init' first."
            }, success=False)

        gates_to_run = []

        if all_gates:
            gates_to_run = ["GATE-00", "GATE-01", "GATE-02", "GATE-03", "GATE-04", "GATE-05"]
        elif gate:
            gates_to_run = [gate.upper()]
        else:
            # Default: run up to current gate
            gates_to_run = [f"GATE-{i:02d}" for i in range(session.get("current_gate", 0) + 1)]

        results = {}
        all_passed = True

        for g in gates_to_run:
            passed, details = self.orchestrator.validate_gate(g, session)
            results[g] = {
                "status": "PASS" if passed else "FAIL",
                "details": details
            }

            self.event_bus.emit_simple(f"gate.{g.lower()}", {
                "gate": g,
                "passed": passed,
                "details": details
            })

            if not passed:
                all_passed = False
                if g in ["GATE-00", "GATE-01", "GATE-02", "GATE-03"]:
                    break  # Blocking gates

        return self._output({
            "command": "validate",
            "gates": results,
            "summary": {
                "total": len(gates_to_run),
                "passed": sum(1 for r in results.values() if r["status"] == "PASS"),
                "failed": sum(1 for r in results.values() if r["status"] == "FAIL")
            }
        }, success=all_passed)

    def cmd_resume(self, checkpoint_path: Optional[str] = None,
                   allow_unsafe: bool = False) -> int:
        """
        Resume from checkpoint.

        Args:
            checkpoint_path: Path to checkpoint file (uses default if not provided)
            allow_unsafe: Allow loading pickle checkpoints (UNSAFE)

        Returns:
            Exit code (0 for success)
        """
        checkpoint_file = checkpoint_path or str(
            self.repo_root / "checkpoints" / "checkpoint.json"
        )

        result = self.state_manager.resume_from_checkpoint(
            checkpoint_file, 
            allow_unsafe=allow_unsafe
        )

        if result.get("status") == "RESUMED":
            self.event_bus.emit_simple("session.resume", {
                "session_id": result["session_id"],
                "checkpoint": checkpoint_file,
                "chunk_cursor": result.get("chunk_cursor")
            })

            return self._output({
                "command": "resume",
                "session": {
                    "id": result["session_id"],
                    "status": "RESUMED",
                    "checkpoint": checkpoint_file
                },
                "state": {
                    "gates_passed": result.get("gates_passed", []),
                    "completed_batches": result.get("completed_batches", []),
                    "chunk_cursor": result.get("chunk_cursor"),
                    "open_issues": result.get("open_issues", [])
                }
            })
        else:
            return self._output({
                "command": "resume",
                "error": result.get("error", "Failed to resume from checkpoint"),
                "checkpoint": checkpoint_file
            }, success=False)

    def cmd_login(self, provider: str = "default",
                  api_key: Optional[str] = None) -> int:
        """
        Authenticate with LLM provider.

        Args:
            provider: LLM provider name
            api_key: API key (will prompt if not provided)

        Returns:
            Exit code (0 for success)
        """
        # In interactive mode, prompt for API key if not provided
        if not api_key and self.execution_mode == ExecutionMode.INTERACTIVE:
            import getpass
            api_key = getpass.getpass(f"Enter API key for {provider}: ")

        result = self.state_manager.configure_provider(provider, api_key)

        return self._output({
            "command": "login",
            "provider": provider,
            "status": "AUTHENTICATED" if result.get("success") else "FAILED",
            "message": result.get("message", "")
        }, success=result.get("success", False))

    def cmd_doctor(self, fix: bool = False, rule_id: Optional[str] = None,
                    rules_only: bool = False) -> int:
        """
        Health check and diagnostics.

        ITEM-FEAT-103: Enhanced with Diagnostic Rules Engine.

        Runs comprehensive checks on:
        - Protocol files integrity
        - Configuration validity
        - Dependencies availability
        - Session state consistency
        - Checkpoint validity
        - Diagnostic rules engine checks

        Args:
            fix: Apply auto-fixes where available
            rule_id: Run specific diagnostic rule only
            rules_only: Skip basic checks, run only rules engine

        Returns:
            Exit code (0 if all checks pass)
        """
        checks = []
        rule_results = []

        # Run basic checks unless rules_only is set
        if not rules_only:
            # Check 1: Protocol files
            protocol_md = self.repo_root / "PROTOCOL.md"
            skill_md = self.repo_root / "SKILL.md"
            config_yaml = self.repo_root / "config.yaml"

            checks.append({
                "name": "protocol_files",
                "status": "OK" if protocol_md.exists() else "MISSING",
                "details": f"PROTOCOL.md: {'exists' if protocol_md.exists() else 'missing'}"
            })
            checks.append({
                "name": "skill_config",
                "status": "OK" if skill_md.exists() else "MISSING",
                "details": f"SKILL.md: {'exists' if skill_md.exists() else 'missing'}"
            })
            checks.append({
                "name": "runtime_config",
                "status": "OK" if config_yaml.exists() else "MISSING",
                "details": f"config.yaml: {'exists' if config_yaml.exists() else 'missing'}"
            })

            # Check 2: Directory structure
            required_dirs = ["inputs", "outputs", "checkpoints", "skills", "scripts"]
            for d in required_dirs:
                dir_path = self.repo_root / d
                checks.append({
                    "name": f"directory_{d}",
                    "status": "OK" if dir_path.exists() and dir_path.is_dir() else "MISSING",
                    "details": f"{d}/: {'exists' if dir_path.exists() else 'missing'}"
                })

            # Check 3: Python dependencies
            try:
                import yaml
                checks.append({"name": "pyyaml", "status": "OK", "details": "PyYAML installed"})
            except ImportError:
                checks.append({"name": "pyyaml", "status": "MISSING", "details": "PyYAML not installed"})

            # Check 4: Current session
            session = self.state_manager.get_current_session()
            checks.append({
                "name": "active_session",
                "status": "OK" if session else "NONE",
                "details": f"Session: {session['id'][:8] if session else 'no active session'}"
            })

            # Check 5: Checkpoint validity
            checkpoint_path = self.repo_root / "checkpoints" / "checkpoint.json"
            if checkpoint_path.exists():
                try:
                    with open(checkpoint_path) as f:
                        cp = json.load(f)
                    checks.append({
                        "name": "checkpoint",
                        "status": "OK",
                        "details": f"Valid checkpoint for session {cp.get('session_id', 'unknown')[:8]}"
                    })
                except Exception as e:
                    checks.append({
                        "name": "checkpoint",
                        "status": "INVALID",
                        "details": f"Checkpoint parse error: {str(e)}"
                    })
            else:
                checks.append({
                    "name": "checkpoint",
                    "status": "NONE",
                    "details": "No checkpoint file found"
                })

        # Run diagnostic rules engine
        try:
            from diagnostics.doctor_rules import DiagnosticRulesEngine
            
            engine = DiagnosticRulesEngine(repo_root=self.repo_root)
            engine.load_rules("diagnostics/rules.yaml")
            
            if rule_id:
                # Run specific rule
                try:
                    result = engine.run_rule(rule_id)
                    if fix and not result.passed and result.auto_fix_available:
                        engine.apply_auto_fix(result)
                    rule_results = [result]
                except ValueError as e:
                    return self._output({
                        "command": "doctor",
                        "error": str(e),
                        "checks": checks
                    }, success=False)
            else:
                # Run all rules
                rule_results = engine.run_all()
                
                # Apply auto-fixes if requested
                if fix:
                    for result in rule_results:
                        if not result.passed and result.auto_fix_available:
                            engine.apply_auto_fix(result)
            
        except ImportError:
            # Rules engine not available, continue with basic checks only
            pass

        # Combine results
        basic_ok = all(c["status"] in ("OK", "NONE") for c in checks)
        rules_ok = all(r.passed for r in rule_results) if rule_results else True
        all_ok = basic_ok and rules_ok

        # Build summary
        summary = {
            "total": len(checks) + len(rule_results),
            "basic_checks": {
                "total": len(checks),
                "ok": sum(1 for c in checks if c["status"] == "OK"),
                "warnings": sum(1 for c in checks if c["status"] == "NONE"),
                "errors": sum(1 for c in checks if c["status"] not in ("OK", "NONE"))
            },
            "rule_checks": {
                "total": len(rule_results),
                "passed": sum(1 for r in rule_results if r.passed),
                "failed": sum(1 for r in rule_results if not r.passed),
                "auto_fixes_applied": sum(1 for r in rule_results if r.auto_fix_applied)
            }
        }

        return self._output({
            "command": "doctor",
            "checks": checks,
            "rule_results": [r.to_dict() for r in rule_results],
            "summary": summary,
            "fix_applied": fix
        }, success=all_ok)

    def cmd_status(self) -> int:
        """
        Show current session status.

        Returns:
            Exit code (0 for success)
        """
        session = self.state_manager.get_current_session()

        if not session:
            return self._output({
                "command": "status",
                "session": None,
                "message": "No active session. Run 'titan init' to start."
            })

        return self._output({
            "command": "status",
            "session": {
                "id": session["id"],
                "status": session.get("status", "UNKNOWN"),
                "created_at": session.get("created_at"),
                "current_phase": session.get("current_phase"),
                "current_gate": session.get("current_gate"),
                "chunk_cursor": session.get("chunk_cursor"),
                "budget_used": session.get("tokens_used", 0),
                "budget_max": session.get("max_tokens", 100000)
            },
            "state_snapshot": session.get("state_snapshot", {}),
            "open_issues": session.get("open_issues", [])
        })

    def cmd_process(self, phase: Optional[str] = None,
                    batch_size: int = 5) -> int:
        """
        Process input files through the pipeline.

        Args:
            phase: Start from specific phase (0-5)
            batch_size: Number of batches per checkpoint

        Returns:
            Exit code (0 for success)
        """
        session = self.state_manager.get_current_session()

        if not session:
            return self._output({
                "command": "process",
                "error": "No active session. Run 'titan init' first."
            }, success=False)

        # Run orchestrator
        result = self.orchestrator.run_pipeline(
            session,
            start_phase=phase,
            batch_size=batch_size
        )

        self.event_bus.emit_simple("pipeline.complete", {
            "session_id": session["id"],
            "result": result
        })

        return self._output({
            "command": "process",
            "pipeline_result": result,
            "gates_passed": session.get("gates_passed", []),
            "artifacts": result.get("artifacts", [])
        }, success=result.get("success", False))

    def cmd_compact(self, strategy: str = "auto") -> int:
        """
        Trigger context compaction.

        Args:
            strategy: Compaction strategy (auto, aggressive, minimal)

        Returns:
            Exit code (0 for success)
        """
        session = self.state_manager.get_current_session()

        if not session:
            return self._output({
                "command": "compact",
                "error": "No active session"
            }, success=False)

        result = self.state_manager.compact_context(strategy)

        return self._output({
            "command": "compact",
            "strategy": strategy,
            "result": result
        }, success=result.get("success", False))

    def cmd_export(self, format: str = "json",
                   output_dir: Optional[str] = None) -> int:
        """
        Export session artifacts.

        Args:
            format: Export format (json, markdown, html)
            output_dir: Output directory (defaults to outputs/)

        Returns:
            Exit code (0 for success)
        """
        session = self.state_manager.get_current_session()

        if not session:
            return self._output({
                "command": "export",
                "error": "No active session"
            }, success=False)

        output_path = Path(output_dir) if output_dir else self.repo_root / "outputs"
        output_path.mkdir(parents=True, exist_ok=True)

        result = self.state_manager.export_artifacts(
            session,
            output_path=output_path,
            format=format
        )

        return self._output({
            "command": "export",
            "format": format,
            "output_dir": str(output_path),
            "artifacts": result.get("artifacts", [])
        }, success=result.get("success", False))

    def cmd_audit_verify(self, audit_path: Optional[str] = None,
                         public_key: Optional[str] = None) -> int:
        """
        Verify audit trail integrity and signatures.

        ITEM-SEC-05: Audit verification command.

        Args:
            audit_path: Path to audit trail file (uses default if not provided)
            public_key: Optional public key hex for signature verification

        Returns:
            Exit code (0 if valid)
        """
        # Determine audit path
        if audit_path:
            audit_file = Path(audit_path)
        else:
            audit_file = self.repo_root / ".titan" / "audit_trail.json"

        if not audit_file.exists():
            return self._output({
                "command": "audit-verify",
                "error": f"Audit trail not found: {audit_file}"
            }, success=False)

        try:
            with open(audit_file) as f:
                audit_data = json.load(f)
        except json.JSONDecodeError as e:
            return self._output({
                "command": "audit-verify",
                "error": f"Invalid audit trail JSON: {e}"
            }, success=False)

        results = {
            "file": str(audit_file),
            "valid": True,
            "errors": [],
            "warnings": [],
            "events_checked": 0,
            "signatures_verified": 0,
            "signatures_failed": 0
        }

        # Import audit modules
        try:
            from events.audit_trail import AuditTrail
            from events.audit_signer import AuditSigner, verify_audit_event
            AUDIT_AVAILABLE = True
        except ImportError:
            AUDIT_AVAILABLE = False

        events = audit_data.get("events", [])
        results["events_checked"] = len(events)

        if not events:
            return self._output({
                "command": "audit-verify",
                **results,
                "message": "No events to verify"
            })

        # Verify hash chain integrity
        for i, event in enumerate(events):
            # Check required fields
            if "event_hash" not in event:
                results["errors"].append({
                    "type": "missing_hash",
                    "event_index": i
                })
                results["valid"] = False
                continue

            # Check chain linkage
            if i > 0:
                expected_previous = events[i - 1].get("event_hash")
                actual_previous = event.get("previous_hash")
                if expected_previous != actual_previous:
                    results["errors"].append({
                        "type": "chain_broken",
                        "event_index": i,
                        "expected": expected_previous,
                        "actual": actual_previous
                    })
                    results["valid"] = False

            # Verify signature if present
            if "signature" in event and AUDIT_AVAILABLE:
                try:
                    pk = bytes.fromhex(public_key) if public_key else None
                    if verify_audit_event(event, pk):
                        results["signatures_verified"] += 1
                    else:
                        results["signatures_failed"] += 1
                        results["warnings"].append({
                            "type": "signature_invalid",
                            "event_index": i,
                            "event_id": event.get("event_id")
                        })
                except Exception as e:
                    results["warnings"].append({
                        "type": "signature_error",
                        "event_index": i,
                        "error": str(e)
                    })

        # Verify Merkle root
        if AUDIT_AVAILABLE:
            try:
                trail = AuditTrail()
                trail.import_trail(audit_data)
                integrity = trail.verify_integrity()

                if not integrity.get("valid"):
                    results["errors"].extend(integrity.get("errors", []))
                    results["valid"] = False

                results["merkle_root"] = trail.get_merkle_root()
            except Exception as e:
                results["warnings"].append({
                    "type": "merkle_verification_error",
                    "error": str(e)
                })

        # Summary
        results["summary"] = {
            "status": "PASS" if results["valid"] else "FAIL",
            "events": results["events_checked"],
            "signatures_ok": results["signatures_verified"],
            "signatures_failed": results["signatures_failed"],
            "errors": len(results["errors"]),
            "warnings": len(results["warnings"])
        }

        return self._output({
            "command": "audit-verify",
            **results
        }, success=results["valid"])


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for TITAN CLI."""
    parser = argparse.ArgumentParser(
        prog="titan",
        description="TITAN FUSE Protocol - Harness-First LLM Agent CLI"
    )

    # Global options
    parser.add_argument(
        "--format", "-f",
        choices=["json", "text", "markdown"],
        default="json",
        help="Output format"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["interactive", "batch", "agent-run"],
        default="interactive",
        help="Execution mode"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new session")
    init_parser.add_argument("--session-id", help="Session identifier")
    init_parser.add_argument("--max-tokens", type=int, default=100000, help="Max tokens")
    init_parser.add_argument("input_files", nargs="*", help="Input files to process")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Run validation gates")
    validate_parser.add_argument("--gate", "-g", help="Specific gate to validate")
    validate_parser.add_argument("--all", "-a", action="store_true", help="Run all gates")

    # resume command
    resume_parser = subparsers.add_parser("resume", help="Resume from checkpoint")
    resume_parser.add_argument("checkpoint", nargs="?", help="Checkpoint file path")
    resume_parser.add_argument("--unsafe", action="store_true",
                               help="Allow loading pickle checkpoints (UNSAFE)")

    # login command
    login_parser = subparsers.add_parser("login", help="Authenticate with LLM provider")
    login_parser.add_argument("--provider", "-p", default="default", help="Provider name")
    login_parser.add_argument("--api-key", "-k", help="API key")

    # doctor command - ITEM-FEAT-103: Enhanced with rules engine
    doctor_parser = subparsers.add_parser("doctor", help="Health check and diagnostics")
    doctor_parser.add_argument("--fix", "-f", action="store_true",
                               help="Apply auto-fixes where available")
    doctor_parser.add_argument("--rule", "-r", dest="rule_id",
                               help="Run specific diagnostic rule")
    doctor_parser.add_argument("--rules-only", action="store_true",
                               help="Run only rules engine checks (skip basic checks)")

    # status command
    subparsers.add_parser("status", help="Show session status")

    # process command
    process_parser = subparsers.add_parser("process", help="Process input files")
    process_parser.add_argument("--phase", help="Start from phase")
    process_parser.add_argument("--batch-size", type=int, default=5, help="Batches per checkpoint")

    # compact command
    compact_parser = subparsers.add_parser("compact", help="Trigger context compaction")
    compact_parser.add_argument("--strategy", "-s", default="auto",
                                choices=["auto", "aggressive", "minimal"])

    # export command
    export_parser = subparsers.add_parser("export", help="Export session artifacts")
    export_parser.add_argument("--format", "-f", default="json",
                               choices=["json", "markdown", "html"])
    export_parser.add_argument("--output", "-o", help="Output directory")

    # ITEM-SEC-05: audit-verify command
    audit_parser = subparsers.add_parser("audit-verify", help="Verify audit trail integrity")
    audit_parser.add_argument("audit_path", nargs="?", help="Path to audit trail file")
    audit_parser.add_argument("--public-key", "-k", help="Public key hex for signature verification")

    return parser


def main() -> int:
    """Main entry point for TITAN CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Initialize CLI
    cli = TitanCLI(repo_root=args.repo_root)
    cli.set_output_format(args.format)
    cli.set_execution_mode(args.mode)
    cli.verbose = args.verbose

    # Dispatch to command handler
    command_handlers = {
        "init": lambda: cli.cmd_init(
            session_id=args.session_id,
            input_files=args.input_files,
            max_tokens=args.max_tokens
        ),
        "validate": lambda: cli.cmd_validate(
            gate=args.gate,
            all_gates=args.all
        ),
        "resume": lambda: cli.cmd_resume(
            checkpoint_path=args.checkpoint,
            allow_unsafe=getattr(args, 'unsafe', False)
        ),
        "login": lambda: cli.cmd_login(
            provider=args.provider,
            api_key=args.api_key
        ),
        "doctor": lambda: cli.cmd_doctor(
            fix=getattr(args, 'fix', False),
            rule_id=getattr(args, 'rule_id', None),
            rules_only=getattr(args, 'rules_only', False)
        ),
        "status": lambda: cli.cmd_status(),
        "process": lambda: cli.cmd_process(
            phase=args.phase,
            batch_size=args.batch_size
        ),
        "compact": lambda: cli.cmd_compact(
            strategy=args.strategy
        ),
        "export": lambda: cli.cmd_export(
            format=args.format,
            output_dir=args.output
        ),
        "audit-verify": lambda: cli.cmd_audit_verify(
            audit_path=getattr(args, 'audit_path', None),
            public_key=getattr(args, 'public_key', None)
        )
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler()
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
