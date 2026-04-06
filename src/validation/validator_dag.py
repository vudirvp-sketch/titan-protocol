"""
Validator Dependency DAG for TITAN FUSE Protocol.

Manages validator dependencies and prevents circular validator calls.

Author: TITAN FUSE Team
Version: 3.2.3
"""

from typing import Dict, List, Set, Tuple, Optional, Callable, Any
from collections import defaultdict
from dataclasses import dataclass, field
import logging


@dataclass
class ValidationResult:
    """Result of validator DAG validation."""
    valid: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    cycle_detected: bool = False
    cycle_path: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "violations": self.violations,
            "warnings": self.warnings,
            "execution_order": self.execution_order,
            "cycle_detected": self.cycle_detected,
            "cycle_path": self.cycle_path
        }


class ValidatorDAG:
    """
    Manage validator dependencies and execution order.

    Provides:
    - Cycle detection to prevent circular dependencies
    - Topological ordering for correct execution sequence
    - Dependency resolution for transitive dependencies

    Usage:
        dag = ValidatorDAG()
        dag.register("security_check", dependencies=["syntax_check"])
        dag.register("syntax_check")  # No dependencies

        result = dag.validate_graph()
        if result.valid:
            order = dag.topological_order()
            # Execute validators in order
    """

    def __init__(self):
        self.graph: Dict[str, List[str]] = defaultdict(list)
        self.validators: Set[str] = set()
        self._execution_cache: Optional[List[str]] = None
        self._logger = logging.getLogger(__name__)

    def register(self, validator_id: str, dependencies: List[str] = None,
                handler: Callable = None) -> None:
        """
        Register validator with its dependencies.

        Args:
            validator_id: Unique identifier for the validator
            dependencies: List of validator IDs that must run first
            handler: Optional handler function for the validator
        """
        self.validators.add(validator_id)
        for dep in (dependencies or []):
            self.graph[validator_id].append(dep)
            self.validators.add(dep)

        self._execution_cache = None  # Invalidate cache
        self._logger.debug(f"Registered validator: {validator_id}, deps: {dependencies}")

    def unregister(self, validator_id: str) -> bool:
        """
        Unregister a validator.

        Returns:
            True if validator was removed, False if not found
        """
        if validator_id not in self.validators:
            return False

        self.validators.discard(validator_id)
        if validator_id in self.graph:
            del self.graph[validator_id]

        # Remove from dependency lists
        for deps in self.graph.values():
            if validator_id in deps:
                deps.remove(validator_id)

        self._execution_cache = None
        self._logger.debug(f"Unregistered validator: {validator_id}")
        return True

    def detect_cycle(self) -> Tuple[bool, List[str]]:
        """
        Detect if graph contains a cycle.

        Returns:
            Tuple of (has_cycle, cycle_path)
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {v: WHITE for v in self.validators}

        def dfs(node: str, path: List[str]) -> List[str]:
            color[node] = GRAY
            for neighbor in self.graph.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    return path + [neighbor]  # Cycle found
                if color[neighbor] == WHITE:
                    cycle = dfs(neighbor, path + [node])
                    if cycle:
                        return cycle
            color[node] = BLACK
            return []

        for validator in self.validators:
            if color[validator] == WHITE:
                cycle = dfs(validator, [])
                if cycle:
                    self._logger.warning(f"Cycle detected: {' -> '.join(cycle)}")
                    return True, cycle

        return False, []

    def topological_order(self) -> List[str]:
        """
        Get validators in topological order.

        Returns:
            List of validator IDs in execution order, or empty if cycle exists
        """
        if self._execution_cache:
            return self._execution_cache

        # Check for cycle first
        has_cycle, _ = self.detect_cycle()
        if has_cycle:
            self._logger.error("Cannot get topological order: cycle detected")
            return []

        result = []
        visited = set()
        temp_visited = set()

        def visit(node: str) -> bool:
            if node in temp_visited:
                return False  # Cycle (shouldn't happen after detect_cycle)
            if node in visited:
                return True

            temp_visited.add(node)
            for dep in self.graph.get(node, []):
                if not visit(dep):
                    return False

            temp_visited.remove(node)
            visited.add(node)
            result.append(node)
            return True

        # Sort for deterministic order
        for validator in sorted(self.validators):
            if validator not in visited:
                if not visit(validator):
                    return []

        self._execution_cache = result
        return result

    def get_dependencies(self, validator_id: str) -> List[str]:
        """
        Get all dependencies for a validator (transitive).

        Args:
            validator_id: Validator to get dependencies for

        Returns:
            List of all transitive dependency IDs
        """
        deps = set()
        to_visit = list(self.graph.get(validator_id, []))

        while to_visit:
            dep = to_visit.pop()
            if dep not in deps:
                deps.add(dep)
                to_visit.extend(self.graph.get(dep, []))

        return list(deps)

    def get_dependents(self, validator_id: str) -> List[str]:
        """
        Get all validators that depend on this one.

        Args:
            validator_id: Validator to get dependents for

        Returns:
            List of validator IDs that depend on this one
        """
        dependents = []
        for vid, deps in self.graph.items():
            if validator_id in deps:
                dependents.append(vid)
        return dependents

    def validate_graph(self) -> ValidationResult:
        """
        Validate the DAG and return result.

        Returns:
            ValidationResult with validity, violations, and execution order
        """
        has_cycle, cycle_path = self.detect_cycle()

        if has_cycle:
            return ValidationResult(
                valid=False,
                violations=[
                    f"[gap: validator_cycle_detected] Cycle: {' -> '.join(cycle_path)}"
                ],
                cycle_detected=True,
                cycle_path=cycle_path
            )

        order = self.topological_order()

        warnings = []
        if len(order) != len(self.validators):
            unreachable = self.validators - set(order)
            warnings.append(f"Some validators not reachable: {unreachable}")

        return ValidationResult(
            valid=True,
            execution_order=order,
            warnings=warnings
        )

    def get_execution_plan(self) -> Dict[str, Any]:
        """
        Get complete execution plan.

        Returns:
            Dict with order, dependencies, and validation status
        """
        result = self.validate_graph()
        return {
            "valid": result.valid,
            "execution_order": result.execution_order,
            "violations": result.violations,
            "warnings": result.warnings,
            "total_validators": len(self.validators),
            "dependency_count": sum(len(deps) for deps in self.graph.values())
        }

    def clear(self) -> None:
        """Clear all validators."""
        self.graph.clear()
        self.validators.clear()
        self._execution_cache = None
        self._logger.debug("DAG cleared")

    def __len__(self) -> int:
        """Return number of validators."""
        return len(self.validators)

    def __contains__(self, validator_id: str) -> bool:
        """Check if validator is registered."""
        return validator_id in self.validators
