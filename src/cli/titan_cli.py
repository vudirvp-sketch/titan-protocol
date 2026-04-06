#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Unified CLI Interface
Version: 3.2.0

A harness-first CLI that positions TITAN as an execution layer,
not just a set of prompts. Provides deterministic JSON output
and explicit entry points for all operations.
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from state.state_manager import StateManager
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
        # Initialize state
        session = self.state_manager.create_session(
            session_id=session_id,
            max_tokens=max_tokens,
            input_files=input_files or []
        )

        # Emit initialization event
        self.event_bus.emit("session.init", {
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

            self.event_bus.emit(f"gate.{g.lower()}", {
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

    def cmd_resume(self, checkpoint_path: Optional[str] = None) -> int:
        """
        Resume from checkpoint.

        Args:
            checkpoint_path: Path to checkpoint file (uses default if not provided)

        Returns:
            Exit code (0 for success)
        """
        checkpoint_file = checkpoint_path or str(
            self.repo_root / "checkpoints" / "checkpoint.json"
        )

        result = self.state_manager.resume_from_checkpoint(checkpoint_file)

        if result.get("status") == "RESUMED":
            self.event_bus.emit("session.resume", {
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

    def cmd_doctor(self) -> int:
        """
        Health check and diagnostics.

        Runs comprehensive checks on:
        - Protocol files integrity
        - Configuration validity
        - Dependencies availability
        - Session state consistency
        - Checkpoint validity

        Returns:
            Exit code (0 if all checks pass)
        """
        checks = []

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

        all_ok = all(c["status"] in ("OK", "NONE") for c in checks)

        return self._output({
            "command": "doctor",
            "checks": checks,
            "summary": {
                "total": len(checks),
                "ok": sum(1 for c in checks if c["status"] == "OK"),
                "warnings": sum(1 for c in checks if c["status"] == "NONE"),
                "errors": sum(1 for c in checks if c["status"] not in ("OK", "NONE"))
            }
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

        self.event_bus.emit("pipeline.complete", {
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

    # login command
    login_parser = subparsers.add_parser("login", help="Authenticate with LLM provider")
    login_parser.add_argument("--provider", "-p", default="default", help="Provider name")
    login_parser.add_argument("--api-key", "-k", help="API key")

    # doctor command
    subparsers.add_parser("doctor", help="Health check and diagnostics")

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
            checkpoint_path=args.checkpoint
        ),
        "login": lambda: cli.cmd_login(
            provider=args.provider,
            api_key=args.api_key
        ),
        "doctor": lambda: cli.cmd_doctor(),
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
