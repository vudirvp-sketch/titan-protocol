"""
Semantic Tainting for TITAN FUSE Protocol.

ITEM-ARCH-19: Tracks data that originates from low-confidence sources
and propagates taint through the data flow.

Provides:
- SemanticTaintTracker: Track and propagate data taint
- Integration with GATE-04 for advisory passes
- Downstream validation requirements

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import hashlib


class TaintSource(Enum):
    """Sources of data taint."""
    GATE_04_ADVISORY = "GATE-04_ADVISORY"
    LOW_CONFIDENCE_LLM = "LOW_CONFIDENCE_LLM"
    EXTERNAL_INPUT = "EXTERNAL_INPUT"
    UNVERIFIED_SOURCE = "UNVERIFIED_SOURCE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    RECOVERED_STATE = "RECOVERED_STATE"


@dataclass
class TaintRecord:
    """Record of a data taint."""
    data_id: str
    source: TaintSource
    confidence: float
    timestamp: str
    reason: str
    propagation_path: List[str] = field(default_factory=list)
    validated: bool = False
    validation_timestamp: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "data_id": self.data_id,
            "source": self.source.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "propagation_path": self.propagation_path,
            "validated": self.validated,
            "validation_timestamp": self.validation_timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TaintRecord':
        return cls(
            data_id=data["data_id"],
            source=TaintSource(data["source"]),
            confidence=data.get("confidence", 0.5),
            timestamp=data["timestamp"],
            reason=data.get("reason", ""),
            propagation_path=data.get("propagation_path", []),
            validated=data.get("validated", False),
            validation_timestamp=data.get("validation_timestamp")
        )


class SemanticTaintTracker:
    """
    Track and propagate semantic taint through data flow.
    
    ITEM-ARCH-19: Taint tracking for low-confidence data.
    
    Data is marked as tainted when it originates from:
    - GATE-04 advisory pass (low confidence output)
    - LLM responses below confidence threshold
    - External/unverified inputs
    - Manual overrides
    
    Taint propagates to derived data, requiring re-validation
    before use in critical operations.
    
    Usage:
        tracker = SemanticTaintTracker()
        
        # Mark data as tainted
        tracker.mark_tainted("output_1", "GATE-04_ADVISORY", 0.7)
        
        # Check if data is tainted
        if tracker.is_tainted("output_1"):
            print("Requires re-validation")
        
        # Propagate taint to dependent data
        tracker.propagate_taint("output_1", "derived_output")
        
        # Validate tainted data
        tracker.validate("output_1")
    """
    
    DEFAULT_CONFIDENCE_THRESHOLD = 0.8
    
    def __init__(self, confidence_threshold: float = None):
        """
        Initialize taint tracker.
        
        Args:
            confidence_threshold: Below this value, data is auto-tainted
        """
        self._taints: Dict[str, TaintRecord] = {}
        self._propagation_graph: Dict[str, Set[str]] = {}  # source -> targets
        self._confidence_threshold = (
            confidence_threshold or self.DEFAULT_CONFIDENCE_THRESHOLD
        )
        self._logger = logging.getLogger(__name__)
    
    @staticmethod
    def generate_data_id(data: Any) -> str:
        """
        Generate a unique ID for data based on its content.
        
        Args:
            data: Data to generate ID for
            
        Returns:
            SHA-256 hash of data
        """
        if isinstance(data, str):
            content = data.encode('utf-8')
        elif isinstance(data, bytes):
            content = data
        else:
            content = str(data).encode('utf-8')
        
        return hashlib.sha256(content).hexdigest()[:16]
    
    def mark_tainted(self, data_id: str, source: str, 
                     confidence: float, reason: str = "") -> TaintRecord:
        """
        Mark data as tainted.
        
        Args:
            data_id: Unique identifier for the data
            source: Source of taint (TaintSource enum value or string)
            confidence: Confidence level of the source (0.0-1.0)
            reason: Human-readable reason for taint
            
        Returns:
            The created TaintRecord
        """
        # Convert string source to enum if needed
        if isinstance(source, str):
            try:
                source_enum = TaintSource(source)
            except ValueError:
                source_enum = TaintSource.UNVERIFIED_SOURCE
        else:
            source_enum = source
        
        record = TaintRecord(
            data_id=data_id,
            source=source_enum,
            confidence=confidence,
            timestamp=datetime.utcnow().isoformat() + "Z",
            reason=reason,
            propagation_path=[data_id]
        )
        
        self._taints[data_id] = record
        
        self._logger.info(
            f"Data tainted: {data_id} from {source_enum.value}, "
            f"confidence={confidence:.2f}"
        )
        
        return record
    
    def is_tainted(self, data_id: str) -> bool:
        """
        Check if data is tainted.
        
        Args:
            data_id: Data identifier to check
            
        Returns:
            True if data is tainted
        """
        record = self._taints.get(data_id)
        return record is not None and not record.validated
    
    def get_taint_source(self, data_id: str) -> Optional[Dict]:
        """
        Get taint information for data.
        
        Args:
            data_id: Data identifier
            
        Returns:
            Dict with taint details, or None if not tainted
        """
        record = self._taints.get(data_id)
        if record:
            return record.to_dict()
        return None
    
    def propagate_taint(self, source_id: str, target_id: str,
                       reason: str = "") -> Optional[TaintRecord]:
        """
        Propagate taint from source to target.
        
        Args:
            source_id: ID of tainted source data
            target_id: ID of derived data
            reason: Reason for propagation
            
        Returns:
            New TaintRecord if propagation occurred, None otherwise
        """
        source_record = self._taints.get(source_id)
        
        if not source_record:
            self._logger.debug(
                f"Cannot propagate: source {source_id} not tainted"
            )
            return None
        
        if source_record.validated:
            self._logger.debug(
                f"Source {source_id} validated, taint not propagated"
            )
            return None
        
        # Add to propagation graph
        if source_id not in self._propagation_graph:
            self._propagation_graph[source_id] = set()
        self._propagation_graph[source_id].add(target_id)
        
        # Create taint record for target
        propagation_path = source_record.propagation_path + [target_id]
        
        record = TaintRecord(
            data_id=target_id,
            source=source_record.source,
            confidence=source_record.confidence,  # Inherit confidence
            timestamp=datetime.utcnow().isoformat() + "Z",
            reason=reason or f"Propagated from {source_id}",
            propagation_path=propagation_path
        )
        
        self._taints[target_id] = record
        
        self._logger.info(
            f"Taint propagated: {source_id} -> {target_id}"
        )
        
        return record
    
    def validate(self, data_id: str, force: bool = False) -> bool:
        """
        Mark tainted data as validated.
        
        Args:
            data_id: Data identifier to validate
            force: Validate even if taint exists
            
        Returns:
            True if validation succeeded
        """
        record = self._taints.get(data_id)
        
        if not record:
            self._logger.debug(f"Data {data_id} not tainted, no validation needed")
            return True
        
        if record.validated:
            self._logger.debug(f"Data {data_id} already validated")
            return True
        
        record.validated = True
        record.validation_timestamp = datetime.utcnow().isoformat() + "Z"
        
        self._logger.info(f"Data validated: {data_id}")
        
        return True
    
    def get_tainted_dependencies(self, data_id: str) -> List[str]:
        """
        Get all tainted data that this data depends on.
        
        Args:
            data_id: Data identifier
            
        Returns:
            List of tainted dependency IDs
        """
        record = self._taints.get(data_id)
        if not record:
            return []
        
        # Get all items in propagation path except self
        dependencies = [
            dep for dep in record.propagation_path
            if dep != data_id and self.is_tainted(dep)
        ]
        
        return dependencies
    
    def get_dependents(self, data_id: str) -> List[str]:
        """
        Get all data that depends on this tainted data.
        
        Args:
            data_id: Source data identifier
            
        Returns:
            List of dependent data IDs
        """
        dependents = []
        
        # Direct dependents
        direct = self._propagation_graph.get(data_id, set())
        dependents.extend(direct)
        
        # Transitive dependents
        for dep in list(direct):
            dependents.extend(self.get_dependents(dep))
        
        return list(set(dependents))
    
    def requires_validation(self, data_id: str) -> Tuple[bool, str]:
        """
        Check if data requires validation before use.
        
        Args:
            data_id: Data identifier
            
        Returns:
            Tuple of (requires_validation, reason)
        """
        record = self._taints.get(data_id)
        
        if not record:
            return False, "Data is not tainted"
        
        if record.validated:
            return False, "Data has been validated"
        
        deps = self.get_tainted_dependencies(data_id)
        if deps:
            return True, f"Data depends on unvalidated taint: {deps}"
        
        return True, f"Data is tainted from {record.source.value}"
    
    def check_downstream_validation(self, data_id: str) -> Dict:
        """
        Check validation status for data and all its dependencies.
        
        Args:
            data_id: Data identifier
            
        Returns:
            Dict with validation status details
        """
        record = self._taints.get(data_id)
        
        if not record:
            return {
                "data_id": data_id,
                "tainted": False,
                "requires_validation": False
            }
        
        unvalidated_deps = self.get_tainted_dependencies(data_id)
        dependents = self.get_dependents(data_id)
        
        return {
            "data_id": data_id,
            "tainted": True,
            "validated": record.validated,
            "requires_validation": not record.validated,
            "source": record.source.value,
            "confidence": record.confidence,
            "unvalidated_dependencies": unvalidated_deps,
            "dependent_data": dependents,
            "propagation_path": record.propagation_path
        }
    
    def clear_taint(self, data_id: str) -> bool:
        """
        Clear taint from data.
        
        Args:
            data_id: Data identifier
            
        Returns:
            True if taint was cleared
        """
        if data_id in self._taints:
            del self._taints[data_id]
            self._logger.info(f"Taint cleared: {data_id}")
            return True
        return False
    
    def clear_all(self) -> int:
        """
        Clear all taint records.
        
        Returns:
            Number of records cleared
        """
        count = len(self._taints)
        self._taints.clear()
        self._propagation_graph.clear()
        self._logger.info(f"Cleared all taint records: {count}")
        return count
    
    def get_tainted_data(self) -> List[Dict]:
        """Get all currently tainted data."""
        return [
            record.to_dict() 
            for record in self._taints.values() 
            if not record.validated
        ]
    
    def get_stats(self) -> Dict:
        """Get taint tracking statistics."""
        total = len(self._taints)
        validated = sum(1 for r in self._taints.values() if r.validated)
        unvalidated = total - validated
        
        by_source: Dict[str, int] = {}
        for record in self._taints.values():
            source = record.source.value
            by_source[source] = by_source.get(source, 0) + 1
        
        return {
            "total_tainted": total,
            "validated": validated,
            "unvalidated": unvalidated,
            "confidence_threshold": self._confidence_threshold,
            "by_source": by_source,
            "propagation_edges": sum(
                len(targets) for targets in self._propagation_graph.values()
            )
        }
    
    def export_state(self) -> Dict:
        """Export taint state for checkpointing."""
        return {
            "taints": {k: v.to_dict() for k, v in self._taints.items()},
            "propagation_graph": {
                k: list(v) for k, v in self._propagation_graph.items()
            },
            "confidence_threshold": self._confidence_threshold
        }
    
    def import_state(self, state: Dict) -> None:
        """Import taint state from checkpoint."""
        self._taints = {
            k: TaintRecord.from_dict(v) 
            for k, v in state.get("taints", {}).items()
        }
        self._propagation_graph = {
            k: set(v) for k, v in state.get("propagation_graph", {}).items()
        }
        self._confidence_threshold = state.get(
            "confidence_threshold", 
            self.DEFAULT_CONFIDENCE_THRESHOLD
        )
        self._logger.info(f"Imported taint state: {len(self._taints)} records")
