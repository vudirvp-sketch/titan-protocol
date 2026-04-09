#!/usr/bin/env python3
"""
TITAN Protocol - Generate Context Graph Script

CLI tool to generate context_graph.json for a repository.

Usage:
    python scripts/generate_context_graph.py [ROOT_PATH] [OUTPUT_PATH]
    
    ROOT_PATH: Repository root (default: current directory)
    OUTPUT_PATH: Output file path (default: .ai/context_graph.json)

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate context_graph.json for TITAN Protocol"
    )
    parser.add_argument(
        "root_path",
        nargs="?",
        default=".",
        help="Repository root path (default: current directory)"
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=".ai/context_graph.json",
        help="Output file path (default: .ai/context_graph.json)"
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="Directories to exclude"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        from src.navigation.context_graph_builder import build_context_graph
        
        logger.info(f"Building context graph for: {args.root_path}")
        
        graph = build_context_graph(
            root_path=args.root_path,
            output_path=args.output_path,
            exclude_dirs=args.exclude or None
        )
        
        logger.info(f"Generated context graph:")
        logger.info(f"  Nodes: {graph['metadata']['total_nodes']}")
        logger.info(f"  Edges: {graph['metadata']['total_edges']}")
        logger.info(f"  Avg Trust: {graph['metadata']['avg_trust_score']:.3f}")
        logger.info(f"  Trust Distribution: {graph['metadata']['trust_distribution']}")
        
        print(f"\n✓ Context graph saved to: {args.output_path}")
        
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        logger.error("Make sure you're running from the project root")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to generate context graph: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
