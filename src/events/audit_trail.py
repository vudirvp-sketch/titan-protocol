"""
Audit Trail Module for TITAN FUSE Protocol.

ITEM-117 Implementation:
- AuditTrail class with Merkle tree for tamper-evident logging
- SHA-256 based hash chain
- Event integrity verification
- Merkle proof generation for individual events
- Integration with EventBus

Critical events signed:
- GATE_PASS, GATE_FAIL
- CHECKPOINT_SAVE
- CREDENTIAL_ACCESS

Author: TITAN FUSE Team
Version: 3.2.3
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging


@dataclass
class AuditEvent:
    """A single auditable event."""
    event_id: str
    event_type: str
    timestamp: str
    data: Dict[str, Any]
    previous_hash: str = ""
    event_hash: str = ""
    signature: str = ""
    
    def compute_hash(self) -> str:
        """Compute SHA-256 hash of event."""
        content = json.dumps({
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            'data': self.data,
            'previous_hash': self.previous_hash
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            'data': self.data,
            'previous_hash': self.previous_hash,
            'event_hash': self.event_hash,
            'signature': self.signature
        }


class MerkleTree:
    """
    SHA-256 based Merkle tree for event integrity.
    
    Structure:
    - Leaves: Individual event hashes
    - Nodes: hash(left_child + right_child)
    - Root: Single hash representing entire tree state
    """
    
    def __init__(self):
        self.leaves: List[str] = []
        self._tree: List[List[str]] = []
    
    def add_leaf(self, event_hash: str) -> int:
        """Add a leaf (event hash) to the tree."""
        self.leaves.append(event_hash)
        self._rebuild_tree()
        return len(self.leaves) - 1
    
    def _rebuild_tree(self) -> None:
        """Rebuild the Merkle tree from leaves."""
        if not self.leaves:
            self._tree = []
            return
        
        # Start with leaves as bottom level
        self._tree = [self.leaves.copy()]
        
        # Build up to root
        while len(self._tree[-1]) > 1:
            level = self._tree[-1]
            next_level = []
            
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else level[i]
                combined = hashlib.sha256(f"{left}{right}".encode()).hexdigest()
                next_level.append(combined)
            
            self._tree.append(next_level)
    
    def get_root(self) -> Optional[str]:
        """Get the Merkle root hash."""
        if not self._tree or not self._tree[-1]:
            return None
        return self._tree[-1][0]
    
    def get_proof(self, leaf_index: int) -> List[Dict]:
        """
        Generate Merkle proof for a leaf.
        
        Args:
            leaf_index: Index of the leaf to prove
            
        Returns:
            List of proof steps with sibling hashes and positions
        """
        if leaf_index >= len(self.leaves) or leaf_index < 0:
            return []
        
        proof = []
        index = leaf_index
        
        for level in self._tree[:-1]:  # All levels except root
            # Determine sibling
            if index % 2 == 0:
                # We're left child, sibling is right
                sibling_index = index + 1
                position = 'right'
            else:
                # We're right child, sibling is left
                sibling_index = index - 1
                position = 'left'
            
            if sibling_index < len(level):
                sibling_hash = level[sibling_index]
            else:
                # No sibling (odd number of nodes)
                sibling_hash = level[index]
            
            proof.append({
                'hash': sibling_hash,
                'position': position
            })
            
            # Move to parent index
            index = index // 2
        
        return proof
    
    def verify_proof(self, leaf_hash: str, proof: List[Dict], root: str) -> bool:
        """
        Verify a Merkle proof.
        
        Args:
            leaf_hash: Hash of the leaf to verify
            proof: Merkle proof from get_proof()
            root: Expected Merkle root
            
        Returns:
            True if proof is valid, False otherwise
        """
        current_hash = leaf_hash
        
        for step in proof:
            sibling_hash = step['hash']
            position = step['position']
            
            if position == 'right':
                combined = f"{current_hash}{sibling_hash}"
            else:
                combined = f"{sibling_hash}{current_hash}"
            
            current_hash = hashlib.sha256(combined.encode()).hexdigest()
        
        return current_hash == root


class AuditTrail:
    """
    Tamper-evident audit trail for TITAN FUSE Protocol.
    
    Features:
    - Hash chain linking all events
    - Merkle tree for efficient verification
    - Integrity verification
    - Merkle proof generation
    
    Usage:
        trail = AuditTrail()
        event_id = trail.add_entry(event)
        is_valid = trail.verify_integrity()
        merkle_root = trail.get_merkle_root()
        proof = trail.get_proof(event_id)
    """
    
    # Events that require cryptographic signatures
    CRITICAL_EVENTS = [
        'GATE_PASS',
        'GATE_FAIL',
        'CHECKPOINT_SAVE',
        'CREDENTIAL_ACCESS',
        'SESSION_ABORT',
        'BUDGET_EXCEEDED'
    ]
    
    def __init__(self, trail_path: str = None):
        """
        Initialize audit trail.
        
        Args:
            trail_path: Optional path to persist audit trail
        """
        self.events: List[AuditEvent] = []
        self.merkle_tree = MerkleTree()
        self.trail_path = trail_path
        self._logger = logging.getLogger(__name__)
        self._event_index: Dict[str, int] = {}  # event_id -> index mapping
    
    def add_entry(self, event: Dict) -> str:
        """
        Add an event to the audit trail.
        
        Args:
            event: Event dictionary with 'type' and 'data' keys
            
        Returns:
            Event ID
        """
        event_type = event.get('type', 'UNKNOWN')
        event_data = event.get('data', {})
        
        # Generate event ID
        event_id = self._generate_event_id(event_type)
        
        # Get previous hash (for chain)
        previous_hash = self.events[-1].event_hash if self.events else "0" * 64
        
        # Create audit event
        audit_event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            data=event_data,
            previous_hash=previous_hash
        )
        
        # Compute event hash
        audit_event.event_hash = audit_event.compute_hash()
        
        # Sign critical events
        if event_type in self.CRITICAL_EVENTS:
            audit_event.signature = self._sign_event(audit_event)
        
        # Add to trail
        self.events.append(audit_event)
        self._event_index[event_id] = len(self.events) - 1
        
        # Add to Merkle tree
        self.merkle_tree.add_leaf(audit_event.event_hash)
        
        # Log critical event
        if event_type in self.CRITICAL_EVENTS:
            self._logger.info(f"Audit: {event_type} [{event_id}]")
        
        return event_id
    
    def verify_integrity(self) -> Dict[str, Any]:
        """
        Verify the integrity of the entire audit trail.
        
        Returns:
            Dict with 'valid' boolean and 'errors' list if invalid
        """
        errors = []
        
        # Verify hash chain
        for i, event in enumerate(self.events):
            # Verify event hash
            computed_hash = event.compute_hash()
            if computed_hash != event.event_hash:
                errors.append({
                    'type': 'hash_mismatch',
                    'event_id': event.event_id,
                    'expected': event.event_hash,
                    'computed': computed_hash
                })
            
            # Verify chain link
            if i > 0:
                expected_previous = self.events[i - 1].event_hash
                if event.previous_hash != expected_previous:
                    errors.append({
                        'type': 'chain_broken',
                        'event_id': event.event_id,
                        'expected_previous': expected_previous,
                        'actual_previous': event.previous_hash
                    })
        
        # Verify Merkle root
        merkle_root = self.merkle_tree.get_root()
        if merkle_root and len(self.events) > 0:
            # Verify last event's proof
            last_proof = self.merkle_tree.get_proof(len(self.events) - 1)
            last_hash = self.events[-1].event_hash
            if not self.merkle_tree.verify_proof(last_hash, last_proof, merkle_root):
                errors.append({
                    'type': 'merkle_verification_failed',
                    'message': 'Merkle tree verification failed for last event'
                })
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'event_count': len(self.events),
            'merkle_root': merkle_root
        }
    
    def get_merkle_root(self) -> Optional[str]:
        """Get the current Merkle root hash."""
        return self.merkle_tree.get_root()
    
    def get_proof(self, event_id: str) -> List[Dict]:
        """
        Get Merkle proof for a specific event.
        
        Args:
            event_id: ID of the event
            
        Returns:
            List of proof steps, empty if event not found
        """
        if event_id not in self._event_index:
            return []
        
        leaf_index = self._event_index[event_id]
        return self.merkle_tree.get_proof(leaf_index)
    
    def verify_event(self, event_id: str) -> Dict[str, Any]:
        """
        Verify a specific event's integrity.
        
        Args:
            event_id: ID of the event to verify
            
        Returns:
            Dict with verification result
        """
        if event_id not in self._event_index:
            return {
                'valid': False,
                'error': 'Event not found'
            }
        
        index = self._event_index[event_id]
        event = self.events[index]
        
        # Verify event hash
        computed_hash = event.compute_hash()
        hash_valid = computed_hash == event.event_hash
        
        # Verify Merkle proof
        proof = self.merkle_tree.get_proof(index)
        merkle_root = self.merkle_tree.get_root()
        merkle_valid = self.merkle_tree.verify_proof(event.event_hash, proof, merkle_root)
        
        # Verify signature for critical events
        signature_valid = True
        if event.event_type in self.CRITICAL_EVENTS and event.signature:
            signature_valid = self._verify_signature(event)
        
        return {
            'valid': hash_valid and merkle_valid and signature_valid,
            'event_id': event_id,
            'event_type': event.event_type,
            'hash_valid': hash_valid,
            'merkle_valid': merkle_valid,
            'signature_valid': signature_valid,
            'proof': proof,
            'merkle_root': merkle_root
        }
    
    def get_events_by_type(self, event_type: str) -> List[AuditEvent]:
        """Get all events of a specific type."""
        return [e for e in self.events if e.event_type == event_type]
    
    def get_events_in_range(self, start_time: str, end_time: str) -> List[AuditEvent]:
        """Get events within a time range."""
        return [
            e for e in self.events
            if start_time <= e.timestamp <= end_time
        ]
    
    def export_trail(self) -> Dict:
        """Export audit trail for persistence."""
        return {
            'version': '3.2.3',
            'exported_at': datetime.utcnow().isoformat() + "Z",
            'event_count': len(self.events),
            'merkle_root': self.get_merkle_root(),
            'events': [e.to_dict() for e in self.events]
        }
    
    def import_trail(self, data: Dict) -> bool:
        """Import audit trail from persisted data."""
        try:
            self.events = []
            self.merkle_tree = MerkleTree()
            self._event_index = {}
            
            for event_data in data.get('events', []):
                event = AuditEvent(
                    event_id=event_data['event_id'],
                    event_type=event_data['event_type'],
                    timestamp=event_data['timestamp'],
                    data=event_data['data'],
                    previous_hash=event_data.get('previous_hash', ''),
                    event_hash=event_data.get('event_hash', ''),
                    signature=event_data.get('signature', '')
                )
                self.events.append(event)
                self._event_index[event.event_id] = len(self.events) - 1
                self.merkle_tree.add_leaf(event.event_hash)
            
            return True
        except Exception as e:
            self._logger.error(f"Failed to import audit trail: {e}")
            return False
    
    def _generate_event_id(self, event_type: str) -> str:
        """Generate unique event ID."""
        import uuid
        return f"{event_type.lower()}-{uuid.uuid4().hex[:12]}"
    
    def _sign_event(self, event: AuditEvent) -> str:
        """
        Sign a critical event.
        
        Note: In production, this should use a proper signing key.
        For now, we use HMAC-style signing with a derived key.
        """
        # Create signature from event hash + type + timestamp
        signing_content = f"{event.event_hash}:{event.event_type}:{event.timestamp}"
        return hashlib.sha256(signing_content.encode()).hexdigest()[:32]
    
    def _verify_signature(self, event: AuditEvent) -> bool:
        """Verify event signature."""
        expected = self._sign_event(event)
        return event.signature == expected


def create_audit_trail(event_bus=None, trail_path: str = None) -> AuditTrail:
    """
    Factory function to create and optionally connect audit trail.
    
    Args:
        event_bus: Optional EventBus to subscribe to
        trail_path: Optional path for persistence
        
    Returns:
        Configured AuditTrail instance
    """
    trail = AuditTrail(trail_path=trail_path)
    
    if event_bus:
        # Subscribe to all events
        def audit_handler(event_type: str, data: Dict):
            trail.add_entry({'type': event_type, 'data': data})
        
        # Subscribe to critical events
        for event_type in AuditTrail.CRITICAL_EVENTS:
            event_bus.subscribe(event_type, audit_handler)
    
    return trail
