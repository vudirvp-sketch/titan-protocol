#!/usr/bin/env python3
"""
TITAN SAE Inspector - Context Graph Visualization Tool

ITEM-SAE-009: SAE Inspector CLI Entry Point

A command-line interface for inspecting and visualizing the Self-Awareness Engine
components including context graph, trust scores, drift status, and summarization.

Usage:
    sae_inspect inspect [--format=json|table|ascii] [--type=TYPE] [--limit=N]
    sae_inspect trust [--threshold=N] [--tier=TIER]
    sae_inspect drift [--level=LEVEL]
    sae_inspect stale [--fix] [--max-age=N] [--min-trust=N]
    sae_inspect summary [--stages=N]
    sae_inspect graph --output=FILE [--format=dot|mermaid|json|html]

Examples:
    # Inspect context graph
    python scripts/sae_inspect.py inspect --format=table --limit=20

    # Show low trust nodes
    python scripts/sae_inspect.py trust --threshold=0.5

    # Check for moderate+ drift
    python scripts/sae_inspect.py drift --level=MODERATE

    # Find and fix stale nodes
    python scripts/sae_inspect.py stale --fix

    # Show session summary
    python scripts/sae_inspect.py summary

    # Export graph to DOT format
    python scripts/sae_inspect.py graph --output=context.dot --format=dot

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.sae_inspector import (
    SAEInspector,
    OutputFormat,
    create_inspector,
)
from src.context.context_graph import ContextGraph, TrustTier, NodeType
from context.drift_detector import DriftLevel


def setup_logging(verbose: bool = False) -> None:
    """Configure logging level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="sae_inspect",
        description="TITAN SAE Inspector - Context Graph Visualization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s inspect --format=table --limit=20
  %(prog)s trust --threshold=0.5
  %(prog)s drift --level=MODERATE
  %(prog)s stale --fix
  %(prog)s summary --stages=5
  %(prog)s graph --output=context.dot --format=dot
        """
    )
    
    # Global options
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "-c", "--context",
        type=str,
        default=".ai/context_graph.json",
        help="Path to context graph file (default: .ai/context_graph.json)"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Show current context graph")
    inspect_parser.add_argument(
        "--format", "-f",
        choices=["table", "json", "ascii", "summary"],
        default="table",
        help="Output format (default: table)"
    )
    inspect_parser.add_argument(
        "--type", "-t",
        choices=["file", "symbol", "module", "config", "checkpoint", "artifact"],
        help="Filter by node type"
    )
    inspect_parser.add_argument(
        "--limit", "-l",
        type=int,
        default=50,
        help="Maximum nodes to display (default: 50)"
    )
    
    # Trust command
    trust_parser = subparsers.add_parser("trust", help="Display trust scores")
    trust_parser.add_argument(
        "--threshold",
        type=float,
        help="Minimum trust score threshold"
    )
    trust_parser.add_argument(
        "--tier",
        choices=["TIER_1_TRUSTED", "TIER_2_RELIABLE", "TIER_3_UNCERTAIN", "TIER_4_UNTRUSTED"],
        help="Filter by trust tier"
    )
    trust_parser.add_argument(
        "--format", "-f",
        choices=["table", "json"],
        default="table",
        help="Output format"
    )
    
    # Drift command
    drift_parser = subparsers.add_parser("drift", help="Show drift status")
    drift_parser.add_argument(
        "--level",
        choices=["NONE", "MINOR", "MODERATE", "SEVERE"],
        help="Filter by drift level"
    )
    drift_parser.add_argument(
        "--format", "-f",
        choices=["table", "json"],
        default="table",
        help="Output format"
    )
    
    # Stale command
    stale_parser = subparsers.add_parser("stale", help="List stale context nodes")
    stale_parser.add_argument(
        "--fix",
        action="store_true",
        help="Remove stale nodes"
    )
    stale_parser.add_argument(
        "--max-age",
        type=float,
        default=24.0,
        help="Maximum age in hours (default: 24)"
    )
    stale_parser.add_argument(
        "--min-trust",
        type=float,
        default=0.3,
        help="Minimum trust threshold (default: 0.3)"
    )
    
    # Summary command
    summary_parser = subparsers.add_parser("summary", help="Show session summary")
    summary_parser.add_argument(
        "--stages",
        type=int,
        default=5,
        help="Number of recent stages to show (default: 5)"
    )
    
    # Graph command
    graph_parser = subparsers.add_parser("graph", help="Generate graph visualization")
    graph_parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output file path"
    )
    graph_parser.add_argument(
        "--format", "-f",
        choices=["dot", "mermaid", "json", "html"],
        default="dot",
        help="Output format (default: dot)"
    )
    graph_parser.add_argument(
        "--no-trust",
        action="store_true",
        help="Exclude trust scores from visualization"
    )
    
    return parser.parse_args()


def get_output_format(format_str: str) -> OutputFormat:
    """Convert string to OutputFormat enum."""
    return {
        "table": OutputFormat.TABLE,
        "json": OutputFormat.JSON,
        "ascii": OutputFormat.ASCII,
        "summary": OutputFormat.SUMMARY,
    }.get(format_str, OutputFormat.TABLE)


def get_trust_tier(tier_str: str) -> Optional[TrustTier]:
    """Convert string to TrustTier enum."""
    if not tier_str:
        return None
    return TrustTier[tier_str]


def get_drift_level(level_str: str) -> Optional[DriftLevel]:
    """Convert string to DriftLevel enum."""
    if not level_str:
        return None
    return DriftLevel[level_str]


def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)
    
    # Create inspector
    inspector = create_inspector()
    
    # Try to load context graph
    context_path = Path(args.context)
    if context_path.exists():
        result = inspector.load_context(str(context_path))
        if not result.success:
            print(f"⚠️  Warning: {result.message}", file=sys.stderr)
    else:
        print(f"ℹ️  Context graph not found at {args.context}", file=sys.stderr)
        print("   Run with a repository context or specify --context path", file=sys.stderr)
    
    # Execute command
    if args.command is None:
        # No command specified, show help
        print(__doc__)
        return 0
    
    result = None
    
    if args.command == "inspect":
        node_type = NodeType(args.type) if args.type else None
        result = inspector.inspect(
            format=get_output_format(args.format),
            node_type=node_type,
            limit=args.limit
        )
    
    elif args.command == "trust":
        result = inspector.trust(
            threshold=args.threshold,
            tier=get_trust_tier(args.tier) if args.tier else None,
            format=get_output_format(args.format)
        )
    
    elif args.command == "drift":
        result = inspector.drift(
            level=get_drift_level(args.level) if args.level else None,
            format=get_output_format(args.format)
        )
    
    elif args.command == "stale":
        result = inspector.stale(
            fix=args.fix,
            max_age_hours=args.max_age,
            min_trust=args.min_trust
        )
    
    elif args.command == "summary":
        result = inspector.summary(stages=args.stages)
    
    elif args.command == "graph":
        result = inspector.graph(
            output=args.output,
            format=args.format,
            include_trust=not args.no_trust
        )
    
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1
    
    # Output result
    if result:
        print(result.message)
        return 0 if result.success else 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
