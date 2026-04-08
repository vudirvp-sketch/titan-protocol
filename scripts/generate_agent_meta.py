#!/usr/bin/env python3
"""
Agent Metadata Generator for TITAN Protocol.

Generates .meta.yaml files for agent modules by parsing Python AST.

Usage:
    python scripts/generate_agent_meta.py
    python scripts/generate_agent_meta.py --module src/agents/multi_agent_orchestrator.py
"""

import argparse
import ast
import inspect
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ModuleInfo:
    """Extracted module information."""
    name: str
    docstring: str = ""
    classes: List[Dict[str, Any]] = field(default_factory=list)
    functions: List[Dict[str, Any]] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    constants: Dict[str, Any] = field(default_factory=dict)


class AgentMetaGenerator:
    """
    Generates .meta.yaml files for agent modules.
    """

    # Patterns to detect capabilities from method names
    CAPABILITY_PATTERNS = {
        r'.*dispatch.*': 'task_dispatch',
        r'.*register.*': 'registration',
        r'.*resolve.*': 'conflict_resolution',
        r'.*aggregate.*': 'result_aggregation',
        r'.*process.*': 'processing',
        r'.*validate.*': 'validation',
        r'.*analyze.*': 'analysis',
        r'.*score.*': 'scoring',
        r'.*detect.*': 'detection',
        r'.*heartbeat.*': 'health_monitoring',
        r'.*queue.*': 'queue_management',
        r'.*route.*': 'routing',
        r'.*broadcast.*': 'broadcasting',
        r'.*onboard.*': 'onboarding',
    }

    # Common event types emitted by agents
    EVENT_PATTERNS = {
        'agent': ['AGENT_REGISTERED', 'AGENT_UNREGISTERED', 'AGENT_DISPATCHED', 'AGENT_COMPLETED'],
        'task': ['TASK_QUEUED', 'TASK_DISPATCHED', 'TASK_COMPLETED', 'TASK_FAILED'],
        'result': ['RESULT_SUBMITTED', 'RESULTS_AGGREGATED'],
        'message': ['AGENT_MESSAGE', 'PROTOCOL_ERROR'],
        'conflict': ['AGENT_CONFLICT', 'CONFLICT_RESOLVED'],
    }

    def __init__(
        self,
        project_dir: Path = None,
        output_dir: Path = None
    ):
        """
        Initialize the generator.

        Args:
            project_dir: Project root directory
            output_dir: Directory for output metadata files
        """
        self.project_dir = project_dir or Path(".")
        self.output_dir = output_dir or self.project_dir / "src" / "agents"

    def _get_version(self) -> str:
        """Get version from VERSION file."""
        version_file = self.project_dir / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip().split('\n')[0]
        return "0.0.0"

    def parse_module(self, module_path: Path) -> ModuleInfo:
        """
        Parse a Python module using AST.

        Args:
            module_path: Path to Python module

        Returns:
            ModuleInfo with extracted data
        """
        if not module_path.exists():
            raise FileNotFoundError(f"Module not found: {module_path}")

        source = module_path.read_text(encoding='utf-8')
        tree = ast.parse(source)

        info = ModuleInfo(name=module_path.stem)

        # Extract module docstring
        if tree.body and isinstance(tree.body[0], ast.Expr):
            if isinstance(tree.body[0].value, ast.Constant):
                info.docstring = tree.body[0].value.value or ""

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                info.classes.append(self._extract_class_info(node))
            elif isinstance(node, ast.FunctionDef):
                # Only top-level functions
                if node in tree.body:
                    info.functions.append(self._extract_function_info(node))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    info.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    info.imports.append(f"{module}.{alias.name}")

        return info

    def _extract_class_info(self, node: ast.ClassDef) -> Dict[str, Any]:
        """Extract class information from AST node."""
        info = {
            "name": node.name,
            "docstring": ast.get_docstring(node) or "",
            "methods": [],
            "bases": [],
        }

        # Get base classes
        for base in node.bases:
            if isinstance(base, ast.Name):
                info["bases"].append(base.id)
            elif isinstance(base, ast.Attribute):
                info["bases"].append(f"{base.value.id}.{base.attr}")

        # Get methods
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_info = {
                    "name": item.name,
                    "docstring": ast.get_docstring(item) or "",
                    "args": [arg.arg for arg in item.args.args if arg.arg != 'self'],
                }
                info["methods"].append(method_info)

        return info

    def _extract_function_info(self, node: ast.FunctionDef) -> Dict[str, Any]:
        """Extract function information from AST node."""
        return {
            "name": node.name,
            "docstring": ast.get_docstring(node) or "",
            "args": [arg.arg for arg in node.args.args],
        }

    def infer_capabilities(self, info: ModuleInfo) -> List[str]:
        """
        Infer capabilities from module structure.

        Args:
            info: Module information

        Returns:
            List of inferred capabilities
        """
        capabilities: Set[str] = set()

        # Check method names against patterns
        for cls_info in info.classes:
            for method in cls_info.get("methods", []):
                method_name = method["name"].lower()
                for pattern, capability in self.CAPABILITY_PATTERNS.items():
                    if re.match(pattern, method_name):
                        capabilities.add(capability)

        # Check class names
        for cls_info in info.classes:
            class_name = cls_info["name"].lower()
            if 'orchestrator' in class_name:
                capabilities.add('orchestration')
            if 'router' in class_name:
                capabilities.add('routing')
            if 'registry' in class_name:
                capabilities.add('registry_management')
            if 'queue' in class_name:
                capabilities.add('queue_management')
            if 'agent' in class_name:
                capabilities.add('agent_coordination')

        return sorted(capabilities)

    def infer_events(self, info: ModuleInfo) -> List[str]:
        """
        Infer emitted events from module structure.

        Args:
            info: Module information

        Returns:
            List of inferred events
        """
        events: Set[str] = set()

        # Search for event emission patterns in docstrings
        all_docstrings = [info.docstring]
        for cls_info in info.classes:
            all_docstrings.append(cls_info.get("docstring", ""))
            for method in cls_info.get("methods", []):
                all_docstrings.append(method.get("docstring", ""))

        # Search for event patterns
        for docstring in all_docstrings:
            for event_list in self.EVENT_PATTERNS.values():
                for event in event_list:
                    if event in docstring.upper():
                        events.add(event)

        # Search for emit/dispatch patterns in class structure
        for cls_info in info.classes:
            for method in cls_info.get("methods", []):
                method_name = method["name"].lower()
                if 'emit' in method_name or 'dispatch' in method_name:
                    # Look for event types in docstring
                    docstring = method.get("docstring", "").upper()
                    for event_list in self.EVENT_PATTERNS.values():
                        for event in event_list:
                            if event in docstring:
                                events.add(event)

        return sorted(events)

    def generate_metadata(
        self,
        module_path: Path,
        tier: int = 6,
        item_id: str = ""
    ) -> Dict[str, Any]:
        """
        Generate metadata for a module.

        Args:
            module_path: Path to Python module
            tier: Tier level for this module
            item_id: Implementation item ID

        Returns:
            Metadata dictionary
        """
        info = self.parse_module(module_path)
        capabilities = self.infer_capabilities(info)
        events = self.infer_events(info)

        # Extract purpose from docstring
        purpose_lines = info.docstring.strip().split('\n')
        purpose = purpose_lines[0] if purpose_lines else f"Module {info.name}"

        # Build classes list
        classes = [
            {
                "name": cls["name"],
                "purpose": cls["docstring"].split('\n')[0] if cls["docstring"] else ""
            }
            for cls in info.classes
        ]

        metadata = {
            "id": info.name,
            "module": module_path.name,
            "version": self._get_version(),
            "purpose": purpose,
            "tier": tier,
            "item_id": item_id,
            "dependencies": [],
            "capabilities": capabilities,
            "classes": classes,
        }

        if events:
            metadata["events_emitted"] = events

        # Add related modules based on imports
        related = []
        for imp in info.imports:
            if 'src.' in imp and 'agents' not in imp:
                related.append(imp.replace('src.', 'src/').replace('.', '/') + '.py')
        if related:
            metadata["related_modules"] = related[:5]  # Limit to 5

        return metadata

    def generate_all(self) -> List[Path]:
        """
        Generate metadata for all agent modules.

        Returns:
            List of generated metadata file paths
        """
        agents_dir = self.project_dir / "src" / "agents"
        if not agents_dir.exists():
            logger.warning(f"Agents directory not found: {agents_dir}")
            return []

        generated = []

        for module_file in agents_dir.glob("*.py"):
            if module_file.name.startswith("_"):
                continue

            meta_file = module_file.with_suffix(".meta.yaml")

            # Skip if metadata already exists and is complete
            if meta_file.exists():
                logger.info(f"Metadata already exists: {meta_file}")
                continue

            try:
                metadata = self.generate_metadata(module_file)

                # Write metadata
                header = f"""# TITAN Protocol Agent Metadata
# Auto-generated: {datetime.utcnow().isoformat()}Z
# Source: src/agents/{module_file.name}

"""
                with open(meta_file, 'w') as f:
                    f.write(header)
                    yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)

                generated.append(meta_file)
                logger.info(f"Generated: {meta_file}")

            except Exception as e:
                logger.error(f"Failed to generate metadata for {module_file}: {e}")

        return generated


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate .meta.yaml files for agent modules"
    )
    parser.add_argument(
        '--module', '-m',
        type=Path,
        default=None,
        help="Single module to process"
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help="Process all modules in src/agents/"
    )
    parser.add_argument(
        '--project-dir',
        type=Path,
        default=Path("."),
        help="Project root directory"
    )
    parser.add_argument(
        '--tier',
        type=int,
        default=6,
        help="Default tier level for modules"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    generator = AgentMetaGenerator(project_dir=args.project_dir)

    if args.module:
        # Process single module
        metadata = generator.generate_metadata(args.module, tier=args.tier)
        meta_file = args.module.with_suffix(".meta.yaml")

        header = f"""# TITAN Protocol Agent Metadata
# Auto-generated: {datetime.utcnow().isoformat()}Z
# Source: src/agents/{args.module.name}

"""
        with open(meta_file, 'w') as f:
            f.write(header)
            yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)

        print(f"Generated: {meta_file}")

    elif args.all:
        # Process all modules
        generated = generator.generate_all()
        print(f"Generated {len(generated)} metadata files")
        for path in generated:
            print(f"  - {path}")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
