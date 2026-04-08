#!/usr/bin/env python3
"""
Nav Map Generator for TITAN Protocol.

Generates .ai/nav_map.json from agent metadata files.

Usage:
    python scripts/generate_nav_map.py
    python scripts/generate_nav_map.py --output .ai/nav_map.json
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class NavMapGenerator:
    """
    Generates nav_map.json from agent metadata files.
    """

    def __init__(
        self,
        project_dir: Path = None,
        output_path: Path = None
    ):
        """
        Initialize the generator.

        Args:
            project_dir: Project root directory
            output_path: Output path for nav_map.json
        """
        self.project_dir = project_dir or Path(".")
        self.output_path = output_path or self.project_dir / ".ai" / "nav_map.json"
        self.agents_dir = self.project_dir / "src" / "agents"

    def _get_version(self) -> str:
        """Get version from VERSION file."""
        version_file = self.project_dir / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip().split('\n')[0]
        return "0.0.0"

    def load_agent_metadata(self) -> List[Dict[str, Any]]:
        """
        Load all agent metadata files.

        Returns:
            List of agent metadata dictionaries
        """
        agents = []

        if not self.agents_dir.exists():
            logger.warning(f"Agents directory not found: {self.agents_dir}")
            return agents

        for meta_file in self.agents_dir.glob("*.meta.yaml"):
            try:
                with open(meta_file, 'r') as f:
                    meta = yaml.safe_load(f)
                    meta['_source_file'] = str(meta_file)
                    agents.append(meta)
                logger.debug(f"Loaded metadata from {meta_file}")
            except Exception as e:
                logger.error(f"Failed to load {meta_file}: {e}")

        logger.info(f"Loaded {len(agents)} agent metadata files")
        return agents

    def generate_protocol_files(self, agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Generate protocol_files section from agent metadata.

        Args:
            agents: List of agent metadata

        Returns:
            List of protocol file entries
        """
        protocol_files = [
            {
                "path": "AGENTS.md",
                "purpose": "Agent entry point with navigation matrix",
                "tier": -1
            },
            {
                "path": "README.md",
                "purpose": "Human-friendly overview",
                "tier": -1
            },
            {
                "path": "SKILL.md",
                "purpose": "Agent configuration and constraints",
                "tier": -1
            },
            {
                "path": "PROTOCOL.md",
                "purpose": "Full protocol specification",
                "tier": "0-6"
            },
            {
                "path": "AI_MISSION.md",
                "purpose": "System prompt bridge",
                "tier": -1
            },
            {
                "path": "config.yaml",
                "purpose": "Runtime defaults",
                "tier": -1
            },
            {
                "path": ".github/README_META.yaml",
                "purpose": "Single source of truth for protocol metadata",
                "tier": -1
            },
            {
                "path": "schemas/readme_meta.schema.json",
                "purpose": "JSON Schema for README_META validation",
                "tier": -1
            },
        ]

        # Add agent modules
        for agent in agents:
            module = agent.get('module', '')
            if module:
                protocol_files.append({
                    "path": f"src/agents/{module}",
                    "purpose": agent.get('purpose', '').split('\n')[0].strip(),
                    "tier": agent.get('tier', -1),
                    "id": agent.get('id', ''),
                    "capabilities": agent.get('capabilities', []),
                })

        return protocol_files

    def generate_shortcuts(self, agents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate shortcuts section from agent metadata.

        Args:
            agents: List of agent metadata

        Returns:
            Shortcuts dictionary
        """
        shortcuts = {
            "start": {
                "action": "read",
                "target": "AGENTS.md"
            },
            "process": {
                "action": "process",
                "target": "inputs/"
            },
            "resume": {
                "action": "read",
                "target": "checkpoints/checkpoint.json"
            },
            "config": {
                "action": "read",
                "target": "config.yaml"
            },
            "meta": {
                "action": "read",
                "target": ".github/README_META.yaml"
            }
        }

        # Add agent-specific shortcuts
        for agent in agents:
            agent_id = agent.get('id', '')
            module = agent.get('module', '')
            if agent_id and module:
                shortcuts[agent_id] = {
                    "action": "read",
                    "target": f"src/agents/{module}"
                }

        return shortcuts

    def generate_nav_map(self) -> Dict[str, Any]:
        """
        Generate complete nav_map.json.

        Returns:
            nav_map dictionary
        """
        version = self._get_version()
        agents = self.load_agent_metadata()

        nav_map = {
            "version": version,
            "generated": datetime.utcnow().isoformat() + "Z",
            "navigation": {
                "entry_points": {
                    "agents": "AGENTS.md",
                    "human": "README.md",
                    "system": "AI_MISSION.md",
                    "config": "SKILL.md",
                    "meta": ".github/README_META.yaml"
                },
                "protocol_files": self.generate_protocol_files(agents),
                "directories": {
                    "inputs": {
                        "purpose": "Files to process",
                        "type": "input"
                    },
                    "outputs": {
                        "purpose": "Generated artifacts",
                        "type": "output"
                    },
                    "checkpoints": {
                        "purpose": "Session persistence",
                        "type": "state"
                    },
                    "skills/validators": {
                        "purpose": "Custom validators",
                        "type": "extension"
                    },
                    "docs/tiers": {
                        "purpose": "Tier exit criteria documentation",
                        "type": "documentation"
                    },
                    "observability": {
                        "purpose": "Agent metrics and monitoring configuration",
                        "type": "observability"
                    }
                }
            },
            "aliases": {
                "verification_gates": ["GATE-00", "GATE-01", "GATE-02", "GATE-03", "GATE-04", "GATE-05"],
                "gates": "verification_gates",
                "validation": "verification_gates",
                "checks": "verification_gates",
                "chunking": "PRINCIPLE-04",
                "rollback": "TIER 4",
                "failsafe": "TIER 5",
                "invariants": ["INVAR-01", "INVAR-02", "INVAR-03", "INVAR-04", "INVAR-05"]
            },
            "shortcuts": self.generate_shortcuts(agents)
        }

        return nav_map

    def save_nav_map(self, nav_map: Dict[str, Any], output_path: Path = None) -> Path:
        """
        Save nav_map to JSON file.

        Args:
            nav_map: nav_map dictionary
            output_path: Output file path

        Returns:
            Path to saved nav_map
        """
        output_path = output_path or self.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(nav_map, f, indent=2)

        logger.info(f"Saved nav_map to {output_path}")
        return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate nav_map.json from agent metadata"
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help="Output path for nav_map.json"
    )
    parser.add_argument(
        '--project-dir',
        type=Path,
        default=Path("."),
        help="Project root directory"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    generator = NavMapGenerator(
        project_dir=args.project_dir,
        output_path=args.output
    )

    nav_map = generator.generate_nav_map()
    output_path = generator.save_nav_map(nav_map)

    print(f"Generated nav_map.json: {output_path}")
    print(f"Version: {nav_map['version']}")
    print(f"Protocol files: {len(nav_map['navigation']['protocol_files'])}")


if __name__ == '__main__':
    main()
