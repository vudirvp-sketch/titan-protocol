"""
REPL Interface for TITAN Protocol v4.0.0.

ITEM-PROD-02: Command-line interface for interactive debugging.

Provides a Read-Eval-Print Loop for interacting with TITAN sessions:
- status: Show current session status
- step: Execute next step
- continue: Run until breakpoint
- inspect <path>: Inspect state value
- modify <path> <value>: Modify state
- breakpoint <event>: Add breakpoint
- rollback <step>: Rollback to step
- help: Show commands

Author: TITAN FUSE Team
Version: 4.0.0
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING
import json
import logging
import shlex
import sys

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event
    from ..state.state_manager import StateManager
    from ..state.checkpoint_manager import CheckpointManager

from .session import (
    InteractiveSession,
    SessionStatus,
    Breakpoint,
    SessionConfig,
)


class CommandType(Enum):
    """Available REPL commands."""
    STATUS = "status"
    STEP = "step"
    CONTINUE = "continue"
    INSPECT = "inspect"
    MODIFY = "modify"
    BREAKPOINT = "breakpoint"
    ROLLBACK = "rollback"
    HELP = "help"
    QUIT = "quit"
    HISTORY = "history"
    PAUSE = "pause"
    RESUME = "resume"
    LIST = "list"
    CLEAR = "clear"


@dataclass
class CommandResult:
    """
    Result of a REPL command execution.
    
    Attributes:
        success: Whether command executed successfully
        output: Output message to display
        error: Error message if failed
        data: Additional data returned by command
    """
    success: bool
    output: str = ""
    error: Optional[str] = None
    data: Any = None
    
    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"Error: {self.error}" if self.error else "Unknown error"


class TitanREPL:
    """
    REPL interface for TITAN Protocol debugging.
    
    ITEM-PROD-02: Provides interactive command-line interface for:
    - Session status inspection
    - Step-by-step execution
    - State inspection and modification
    - Breakpoint management
    - Rollback to previous steps
    
    Commands:
        status              Show current session status
        step                Execute next step
        continue            Run until breakpoint
        inspect <path>      Inspect state value (dot notation)
        modify <path> <val> Modify state value
        breakpoint <event>  Add breakpoint for event type
        rollback <step>     Rollback to step number
        history [limit]     Show step history
        pause               Pause execution
        resume              Resume execution
        list                List breakpoints
        clear <event>       Clear breakpoint
        help                Show available commands
        quit                Exit REPL
    
    Usage:
        # Programmatic usage
        repl = TitanREPL(event_bus, state_manager, checkpoint_manager)
        result = repl.execute("status")
        print(result.output)
        
        # Interactive mode
        repl.run()
        
        # With callbacks
        def on_breakpoint(bp, event):
            print(f"Breakpoint hit: {bp.event}")
        
        repl = TitanREPL(
            event_bus=event_bus,
            state_manager=state_manager,
            checkpoint_manager=checkpoint_manager,
            on_breakpoint_hit=on_breakpoint
        )
        repl.run()
    """
    
    def __init__(
        self,
        event_bus: "EventBus" = None,
        state_manager: "StateManager" = None,
        checkpoint_manager: "CheckpointManager" = None,
        config: SessionConfig = None,
        on_breakpoint_hit: Callable[[Breakpoint, "Event"], None] = None,
        on_pause: Callable[[], None] = None,
        on_resume: Callable[[], None] = None,
    ):
        """
        Initialize TitanREPL.
        
        Args:
            event_bus: EventBus for event handling
            state_manager: StateManager for state access
            checkpoint_manager: CheckpointManager for rollback
            config: Session configuration
            on_breakpoint_hit: Callback for breakpoint hits
            on_pause: Callback for pause events
            on_resume: Callback for resume events
        """
        self.logger = logging.getLogger(__name__)
        self.config = config or SessionConfig()
        
        # Create interactive session
        self.session = InteractiveSession(
            event_bus=event_bus,
            state_manager=state_manager,
            checkpoint_manager=checkpoint_manager,
            config=self.config,
        )
        
        # Set callbacks
        self.session.set_callbacks(
            on_breakpoint_hit=on_breakpoint_hit,
            on_pause=on_pause,
            on_resume=on_resume,
        )
        
        # REPL state
        self._running = False
        self._command_history: List[str] = []
        self._output_callback: Optional[Callable[[str], None]] = None
        
        # Command handlers
        self._commands: Dict[str, Callable] = {
            "status": self._cmd_status,
            "step": self._cmd_step,
            "continue": self._cmd_continue,
            "c": self._cmd_continue,  # Alias
            "inspect": self._cmd_inspect,
            "i": self._cmd_inspect,  # Alias
            "modify": self._cmd_modify,
            "m": self._cmd_modify,  # Alias
            "breakpoint": self._cmd_breakpoint,
            "bp": self._cmd_breakpoint,  # Alias
            "rollback": self._cmd_rollback,
            "history": self._cmd_history,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "list": self._cmd_list,
            "clear": self._cmd_clear,
            "help": self._cmd_help,
            "?": self._cmd_help,  # Alias
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,  # Alias
            "q": self._cmd_quit,  # Alias
        }
    
    def run(self) -> None:
        """
        Run the REPL interactively.
        
        Starts the interactive session and enters the command loop.
        """
        if not self.config.enabled:
            print("Interactive mode is disabled. Set 'interactive.enabled: true' in config.")
            return
        
        self._running = True
        self.session.start()
        
        print("\n" + "=" * 50)
        print("TITAN Protocol Interactive Debugger v4.0.0")
        print("=" * 50)
        print("Type 'help' for available commands.\n")
        
        try:
            self._load_history()
            while self._running:
                try:
                    # Get input
                    line = input(self.config.prompt).strip()
                    
                    if not line:
                        continue
                    
                    # Add to history
                    self._command_history.append(line)
                    
                    # Execute command
                    result = self.execute(line)
                    
                    # Display result
                    if result.output:
                        print(result.output)
                    if result.error:
                        print(f"Error: {result.error}", file=sys.stderr)
                        
                except KeyboardInterrupt:
                    print("\nUse 'quit' to exit.")
                except EOFError:
                    print("\nGoodbye!")
                    break
                    
        finally:
            self.session.stop()
            self._save_history()
    
    def execute(self, command_line: str) -> CommandResult:
        """
        Execute a command string.
        
        Parses and executes the given command line.
        
        Args:
            command_line: Command string to execute
            
        Returns:
            CommandResult with execution outcome
        """
        # Parse command
        parts = self._parse_command(command_line)
        if not parts:
            return CommandResult(success=True)
        
        cmd = parts[0].lower()
        args = parts[1:]
        
        # Find and execute handler
        if cmd in self._commands:
            try:
                return self._commands[cmd](args)
            except Exception as e:
                self.logger.error(f"Command failed: {e}")
                return CommandResult(success=False, error=str(e))
        else:
            return CommandResult(
                success=False,
                error=f"Unknown command: {cmd}. Type 'help' for available commands."
            )
    
    def _parse_command(self, line: str) -> List[str]:
        """Parse command line into parts."""
        try:
            # Use shlex for proper quote handling
            return shlex.split(line)
        except ValueError:
            # Fallback to simple split on parse error
            return line.split()
    
    def _cmd_status(self, args: List[str]) -> CommandResult:
        """Show current session status."""
        info = self.session.get_status_info()
        
        lines = [
            "Session Status",
            "─" * 40,
            f"  Status:      {info['status']}",
            f"  Step:        {info['step_count']}",
            f"  Paused:      {info['is_paused']}",
            f"  Breakpoints: {len(info['breakpoints'])}",
            f"  History:     {info['history_count']} steps",
        ]
        
        # Add current event info
        if info.get('current_event'):
            event = info['current_event']
            lines.append(f"  Last Event:  {event.get('event_type', 'unknown')}")
        
        # Add breakpoint list
        if info['breakpoints']:
            lines.append("\nActive Breakpoints:")
            for bp in info['breakpoints']:
                status = "enabled" if bp['enabled'] else "disabled"
                hits = bp.get('hit_count', 0)
                lines.append(f"  - {bp['event']} ({status}, hits: {hits})")
        
        return CommandResult(success=True, output="\n".join(lines), data=info)
    
    def _cmd_step(self, args: List[str]) -> CommandResult:
        """Execute next step."""
        if self.session.status not in (SessionStatus.RUNNING, SessionStatus.PAUSED,
                                        SessionStatus.BREAKPOINT_HIT, SessionStatus.STEP_MODE):
            return CommandResult(
                success=False,
                error=f"Cannot step in status: {self.session.status.value}"
            )
        
        self.session.step()
        
        # Get step info
        history = self.session.get_step_history(limit=1)
        step_info = ""
        if history:
            last = history[0]
            event_info = ""
            if last.event:
                event_info = f" - {last.event.get('event_type', 'unknown')}"
            step_info = f"Step {last.step_number}{event_info}"
        
        return CommandResult(
            success=True,
            output=f"Executed step. {step_info}"
        )
    
    def _cmd_continue(self, args: List[str]) -> CommandResult:
        """Continue execution until next breakpoint."""
        if self.session.status not in (SessionStatus.PAUSED, SessionStatus.BREAKPOINT_HIT,
                                        SessionStatus.STEP_MODE):
            return CommandResult(
                success=False,
                error=f"Cannot continue in status: {self.session.status.value}"
            )
        
        self.session.continue_execution()
        return CommandResult(
            success=True,
            output="Continuing execution. Will pause at next breakpoint."
        )
    
    def _cmd_inspect(self, args: List[str]) -> CommandResult:
        """Inspect state value."""
        if not args:
            return CommandResult(
                success=False,
                error="Usage: inspect <path>\nExample: inspect gates.GATE-00.status"
            )
        
        path = args[0]
        value = self.session.inspect(path)
        
        if value is None:
            return CommandResult(
                success=False,
                error=f"Path not found: {path}"
            )
        
        # Format output
        if isinstance(value, dict):
            output = f"{path}:\n{json.dumps(value, indent=2, default=str)}"
        elif isinstance(value, list):
            output = f"{path}: [{len(value)} items]\n{json.dumps(value, indent=2, default=str)}"
        else:
            output = f"{path}: {value}"
        
        return CommandResult(success=True, output=output, data={"path": path, "value": value})
    
    def _cmd_modify(self, args: List[str]) -> CommandResult:
        """Modify state value."""
        if len(args) < 2:
            return CommandResult(
                success=False,
                error="Usage: modify <path> <value>\nExample: modify gates.GATE-00.status PASS"
            )
        
        path = args[0]
        value_str = " ".join(args[1:])
        
        # Try to parse value as JSON, otherwise use as string
        try:
            value = json.loads(value_str)
        except json.JSONDecodeError:
            value = value_str
        
        # Modify state
        self.session.modify(path, value)
        
        return CommandResult(
            success=True,
            output=f"Modified {path} = {json.dumps(value, default=str)}"
        )
    
    def _cmd_breakpoint(self, args: List[str]) -> CommandResult:
        """Add breakpoint."""
        if not args:
            return CommandResult(
                success=False,
                error="Usage: breakpoint <event>\nExample: breakpoint GATE_FAIL"
            )
        
        event = args[0]
        condition = args[1] if len(args) > 1 else None
        
        bp = self.session.add_breakpoint(event, condition)
        
        return CommandResult(
            success=True,
            output=f"Added breakpoint for event: {event}"
        )
    
    def _cmd_rollback(self, args: List[str]) -> CommandResult:
        """Rollback to previous step."""
        if not args:
            # Show available steps
            history = self.session.get_step_history(limit=20)
            if not history:
                return CommandResult(
                    success=False,
                    error="No history available for rollback"
                )
            
            lines = ["Available steps for rollback:"]
            for step in reversed(history):
                event_info = ""
                if step.event:
                    event_info = f" - {step.event.get('event_type', 'unknown')}"
                lines.append(f"  {step.step_number}{event_info}")
            
            return CommandResult(success=True, output="\n".join(lines))
        
        try:
            step_num = int(args[0])
        except ValueError:
            return CommandResult(
                success=False,
                error=f"Invalid step number: {args[0]}"
            )
        
        if self.session.rollback(step_num):
            return CommandResult(
                success=True,
                output=f"Rolled back to step {step_num}"
            )
        else:
            return CommandResult(
                success=False,
                error=f"Failed to rollback to step {step_num}"
            )
    
    def _cmd_history(self, args: List[str]) -> CommandResult:
        """Show step history."""
        limit = 20
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                pass
        
        history = self.session.get_step_history(limit=limit)
        
        if not history:
            return CommandResult(success=True, output="No history available")
        
        lines = [f"Step History (last {len(history)} steps):"]
        lines.append("─" * 50)
        
        for step in history:
            event_info = ""
            if step.event:
                event_type = step.event.get('event_type', 'unknown')
                event_info = f" [{event_type}]"
            lines.append(f"  Step {step.step_number}{event_info}")
            lines.append(f"    Time: {step.timestamp}")
        
        return CommandResult(success=True, output="\n".join(lines))
    
    def _cmd_pause(self, args: List[str]) -> CommandResult:
        """Pause execution."""
        if self.session.status != SessionStatus.RUNNING:
            return CommandResult(
                success=False,
                error=f"Cannot pause in status: {self.session.status.value}"
            )
        
        self.session.pause()
        return CommandResult(success=True, output="Execution paused")
    
    def _cmd_resume(self, args: List[str]) -> CommandResult:
        """Resume execution."""
        if self.session.status != SessionStatus.PAUSED:
            return CommandResult(
                success=False,
                error=f"Cannot resume in status: {self.session.status.value}"
            )
        
        self.session.continue_execution()
        return CommandResult(success=True, output="Execution resumed")
    
    def _cmd_list(self, args: List[str]) -> CommandResult:
        """List breakpoints."""
        breakpoints = self.session.get_breakpoints()
        
        if not breakpoints:
            return CommandResult(success=True, output="No breakpoints set")
        
        lines = ["Breakpoints:"]
        lines.append("─" * 40)
        
        for bp in breakpoints:
            status = "enabled" if bp.enabled else "disabled"
            lines.append(f"  {bp.event} ({status}, hits: {bp.hit_count})")
        
        return CommandResult(success=True, output="\n".join(lines))
    
    def _cmd_clear(self, args: List[str]) -> CommandResult:
        """Clear breakpoint."""
        if not args:
            return CommandResult(
                success=False,
                error="Usage: clear <event>\nExample: clear GATE_FAIL"
            )
        
        event = args[0]
        if self.session.remove_breakpoint(event):
            return CommandResult(success=True, output=f"Cleared breakpoint: {event}")
        else:
            return CommandResult(
                success=False,
                error=f"Breakpoint not found: {event}"
            )
    
    def _cmd_help(self, args: List[str]) -> CommandResult:
        """Show help."""
        help_text = """
TITAN Protocol Interactive Debugger - Commands

Execution Control:
  status              Show current session status
  step                Execute next step
  continue (c)        Run until breakpoint
  pause               Pause execution
  resume              Resume execution

State Inspection:
  inspect <path> (i)  Inspect state value (dot notation)
  modify <path> <val> Modify state value
                       Example: modify gates.GATE-00.status PASS

Breakpoints:
  breakpoint <event>  Add breakpoint for event type
                       Example: breakpoint GATE_FAIL
  list                List all breakpoints
  clear <event>       Clear breakpoint

History & Rollback:
  history [limit]     Show step history
  rollback [step]     Rollback to step (omit step to see options)

Other:
  help (?)            Show this help
  quit (q)            Exit REPL

Event Types for Breakpoints:
  GATE_FAIL, GATE_WARN, GATE_PASS
  BUDGET_WARNING, BUDGET_EXCEEDED
  CHUNK_PROCESSED, CHUNK_COMPLETE
  SESSION_START, SESSION_END
  CHECKPOINT_SAVED
"""
        return CommandResult(success=True, output=help_text.strip())
    
    def _cmd_quit(self, args: List[str]) -> CommandResult:
        """Exit REPL."""
        self._running = False
        return CommandResult(success=True, output="Goodbye!")
    
    def _load_history(self) -> None:
        """Load command history from file."""
        try:
            path = Path(self.config.history_file)
            if path.exists():
                with open(path, 'r') as f:
                    self._command_history = [line.strip() for line in f if line.strip()]
        except Exception as e:
            self.logger.warning(f"Failed to load history: {e}")
    
    def _save_history(self) -> None:
        """Save command history to file."""
        try:
            path = Path(self.config.history_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Keep only recent history
            history = self._command_history[-self.config.max_history:]
            
            with open(path, 'w') as f:
                for line in history:
                    f.write(line + "\n")
        except Exception as e:
            self.logger.warning(f"Failed to save history: {e}")
    
    def set_output_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set callback for output messages.
        
        Useful for non-interactive usage where output should be
        captured rather than printed.
        
        Args:
            callback: Function to call with output strings
        """
        self._output_callback = callback
    
    def get_command_history(self) -> List[str]:
        """Get list of executed commands."""
        return self._command_history.copy()
    
    def __repr__(self) -> str:
        return f"<TitanREPL(status={self.session.status.value}, enabled={self.config.enabled})>"
