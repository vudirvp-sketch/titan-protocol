#!/usr/bin/env python3
"""
TITAN FUSE Protocol Demo Script

Demonstrates the full protocol workflow:
1. Initialize session
2. Process input file through phases
3. Validate gates
4. Generate artifacts
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from state.state_manager import StateManager
from harness.orchestrator import Orchestrator
from events.event_bus import EventBus, EventSeverity


def main():
    print("=" * 60)
    print("TITAN FUSE Protocol v3.2.1 - Demo")
    print("=" * 60)
    
    repo_root = Path(__file__).parent
    input_file = repo_root / "inputs" / "test.md"
    
    # Initialize components
    print("\n[PHASE -1] Bootstrap & Initialization")
    print("-" * 40)
    
    state_manager = StateManager(repo_root)
    orchestrator = Orchestrator(repo_root)
    event_bus = EventBus()
    
    # Subscribe to events
    def on_gate_event(event):
        status = "✓" if event.data.get("passed") else "✗"
        print(f"  {status} {event.data.get('gate')}: {event.data.get('details', {}).get('status', 'UNKNOWN')}")
    
    event_bus.subscribe("gate", on_gate_event)
    
    # Create session
    print("\n[PHASE 0] Session Creation")
    print("-" * 40)
    
    session = state_manager.create_session(
        input_files=[str(input_file)],
        max_tokens=100000
    )
    
    print(f"  Session ID: {session['id'][:8]}...")
    print(f"  Source: {session.get('source_file', 'None')}")
    print(f"  Checksum: {session.get('source_checksum', 'None')[:16]}...")
    
    # Run pipeline
    print("\n[PIPELINE] Processing")
    print("-" * 40)
    
    result = orchestrator.run_pipeline(session)
    
    # Display results
    print("\n[RESULTS]")
    print("-" * 40)
    print(f"  Success: {result.get('success', False)}")
    print(f"  Phases completed: {', '.join(result.get('phases_completed', []))}")
    print(f"  Gates passed: {', '.join(result.get('gates_passed', []))}")
    
    if result.get('warnings'):
        print(f"  Warnings: {result.get('warnings')}")
    
    if result.get('error'):
        print(f"  Error: {result.get('error')}")
    
    # Save checkpoint
    print("\n[CHECKPOINT] Saving session state")
    print("-" * 40)
    
    checkpoint_result = state_manager.save_checkpoint()
    if checkpoint_result.get("success"):
        print(f"  Checkpoint saved: {checkpoint_result.get('checkpoint_path')}")
    else:
        print(f"  Checkpoint failed: {checkpoint_result.get('error')}")
    
    # Session summary
    print("\n[SESSION SUMMARY]")
    print("-" * 40)
    print(f"  Total chunks: {session.get('chunks_total', 0)}")
    print(f"  Open issues: {len(session.get('open_issues', []))}")
    print(f"  Known gaps: {len(session.get('known_gaps', []))}")
    print(f"  Tokens used: {session.get('tokens_used', 0)}")
    
    # Event bus stats
    stats = event_bus.get_stats()
    print(f"\n  Events emitted: {stats.get('total_events', 0)}")
    
    print("\n" + "=" * 60)
    print("Protocol execution complete!")
    print("=" * 60)
    
    return 0 if result.get('success') else 1


if __name__ == "__main__":
    sys.exit(main())
