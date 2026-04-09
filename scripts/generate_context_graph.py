#!/usr/bin/env python3
"""
TITAN Protocol - Context Graph Generator CLI

Command-line interface for generating context_graph.json.

Usage:
    python scripts/generate_context_graph.py [ROOT_PATH] [OUTPUT_PATH] [--exclude DIR1 DIR2 ...]

Examples:
    # Generate for current directory
    python scripts/generate_context_graph.py . .ai/context_graph.json

    # Generate with exclusions
    python scripts/generate_context_graph.py . .ai/context_graph.json --exclude node_modules venv build

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.navigation.context_graph_builder import build_context_graph

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for context graph generator."""
    parser = argparse.ArgumentParser(
        description="Generate context_graph.json for TITAN Protocol"
    )
    parser.add_argument(
        "root_path",
        nargs="?",
        default=".",
        help="Root directory to analyze (default: current directory)"
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=".ai/context_graph.json",
        help="Output path for context_graph.json (default: .ai/context_graph.json)"
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=None,
        help="Directories to exclude from analysis"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"Generating context graph for: {args.root_path}")
    logger.info(f"Output path: {args.output_path}")

    if args.exclude:
        logger.info(f"Excluding directories: {args.exclude}")

    try:
        graph = build_context_graph(
            root_path=args.root_path,
            output_path=args.output_path,
            exclude_dirs=args.exclude
        )

        print(f"\n{'='*60}")
        print("Context Graph Generation Complete")
        print(f"{'='*60}")
        print(f"Total nodes: {graph['metadata']['total_nodes']}")
        print(f"Total edges: {graph['metadata']['total_edges']}")
        print(f"Average trust score: {graph['metadata']['avg_trust_score']:.3f}")
        print(f"\nTrust Distribution:")
        for tier, count in graph['metadata']['trust_distribution'].items():
            print(f"  {tier}: {count}")
        print(f"\nOutput saved to: {args.output_path}")
        print(f"{'='*60}")

        return 0

    except Exception as e:
        logger.error(f"Failed to generate context graph: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
