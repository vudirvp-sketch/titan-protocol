"""
Catalog Versioning Module for TITAN Protocol.

ITEM-FEEDBACK-01: CatalogVersionManager Implementation

This module provides version control for the skill catalog, enabling
tracking of changes, rollback to previous versions, and comparison
between versions.

Features:
- Immutable version snapshots with checksums
- Atomic version creation with integrity verification
- Version listing and filtering by skill
- Rollback to any previous version
- Version diff comparison

Storage:
- Versions are stored in .titan/skills/versions/
- Each version is a JSON file with metadata
- Checksums ensure integrity

Components:
- CatalogVersion: Version record dataclass
- CatalogDiff: Difference between two versions
- CatalogVersionManager: Main version management class

Author: TITAN Protocol Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import hashlib
import json
import logging
import uuid

if TYPE_CHECKING:
    from src.storage.backend import StorageBackend


@dataclass
class CatalogVersion:
    """
    A version record for the skill catalog.
    
    Represents an immutable snapshot of the catalog at a point in time,
    including metadata about why the version was created.
    
    Attributes:
        version_id: Unique identifier for this version
        catalog: The catalog data at this version
        reason: Human-readable reason for the version
        timestamp: When the version was created (ISO 8601)
        checksum: SHA-256 checksum of the catalog for integrity
    
    Example:
        >>> version = CatalogVersion(
        ...     version_id="v-abc123",
        ...     catalog={"skills": {...}, "version": "1.0.0"},
        ...     reason="Initial catalog version"
        ... )
    """
    version_id: str
    catalog: Dict[str, Any]
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    checksum: str = ""
    
    def __post_init__(self):
        """Calculate checksum if not provided."""
        if not self.checksum:
            self.checksum = self._compute_checksum()
    
    def _compute_checksum(self) -> str:
        """
        Compute SHA-256 checksum of the catalog.
        
        Returns:
            Hexadecimal checksum string
        """
        catalog_json = json.dumps(self.catalog, sort_keys=True, default=str)
        return hashlib.sha256(catalog_json.encode('utf-8')).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "version_id": self.version_id,
            "catalog": self.catalog,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "checksum": self.checksum
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CatalogVersion':
        """
        Create from dictionary.
        
        Args:
            data: Dictionary containing version data
            
        Returns:
            CatalogVersion instance
        """
        return cls(
            version_id=data["version_id"],
            catalog=data["catalog"],
            reason=data["reason"],
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z"),
            checksum=data.get("checksum", "")
        )
    
    def verify_integrity(self) -> bool:
        """
        Verify the catalog integrity using checksum.
        
        Returns:
            True if checksum matches, False otherwise
        """
        expected = self._compute_checksum()
        return self.checksum == expected


@dataclass
class CatalogDiff:
    """
    Difference between two catalog versions.
    
    Represents the changes between two versions of the catalog,
    including added, removed, and modified skills.
    
    Attributes:
        version_id_from: Source version ID
        version_id_to: Target version ID
        added_skills: Skills added in the target version
        removed_skills: Skills removed from the source version
        modified_skills: Skills with threshold changes
        timestamp_from: Source version timestamp
        timestamp_to: Target version timestamp
    """
    version_id_from: str
    version_id_to: str
    added_skills: List[str] = field(default_factory=list)
    removed_skills: List[str] = field(default_factory=list)
    modified_skills: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timestamp_from: str = ""
    timestamp_to: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "version_id_from": self.version_id_from,
            "version_id_to": self.version_id_to,
            "added_skills": self.added_skills,
            "removed_skills": self.removed_skills,
            "modified_skills": self.modified_skills,
            "timestamp_from": self.timestamp_from,
            "timestamp_to": self.timestamp_to,
            "summary": {
                "total_changes": len(self.added_skills) + len(self.removed_skills) + len(self.modified_skills),
                "added_count": len(self.added_skills),
                "removed_count": len(self.removed_skills),
                "modified_count": len(self.modified_skills)
            }
        }


class CatalogVersionManager:
    """
    Manages version control for the skill catalog.
    
    Provides atomic version creation, listing, rollback, and diff
    operations for the catalog with integrity verification.
    
    Storage Structure:
        .titan/skills/versions/
        ├── v-{uuid}.json      # Version snapshots
        ├── v-{uuid}.json.meta # Version metadata (optional)
        └── index.json         # Version index
    
    Features:
        - Immutable version snapshots
        - SHA-256 checksum integrity
        - Atomic version creation
        - Rollback support
        - Version diff comparison
        - Skill-specific version filtering
    
    Example:
        >>> from src.storage import LocalStorageBackend
        >>> 
        >>> storage = LocalStorageBackend(base_path="./.titan/storage")
        >>> version_manager = CatalogVersionManager(storage)
        >>> 
        >>> # Create a version
        >>> version_id = version_manager.create_version(catalog, "Initial version")
        >>> 
        >>> # List versions
        >>> versions = version_manager.list_versions()
        >>> 
        >>> # Rollback
        >>> catalog = version_manager.rollback_to_version(version_id)
    """
    
    VERSIONS_PATH = ".titan/skills/versions"
    INDEX_PATH = ".titan/skills/versions/index.json"
    CATALOG_PATH = "skills/catalog.json"
    
    def __init__(self, storage_backend: 'StorageBackend'):
        """
        Initialize the version manager.
        
        Args:
            storage_backend: StorageBackend instance for persistence
        """
        self.storage = storage_backend
        self._version_cache: Dict[str, CatalogVersion] = {}
        self._index_cache: Dict[str, Any] = {}
        
        self._logger = logging.getLogger(__name__)
        
        # Ensure version directory exists
        self._ensure_version_directory()
    
    def _ensure_version_directory(self) -> None:
        """Ensure the versions directory exists."""
        try:
            # Create a placeholder to ensure directory exists
            self.storage.save(
                f"{self.VERSIONS_PATH}/.gitkeep",
                b"",
                {"content_type": "text/plain"}
            )
        except Exception:
            pass  # Directory may already exist
    
    def create_version(self, catalog: Dict[str, Any], reason: str) -> str:
        """
        Create a new version of the catalog.
        
        Creates an immutable snapshot with a checksum for integrity
        verification.
        
        Args:
            catalog: Catalog data to version
            reason: Human-readable reason for the version
            
        Returns:
            Version ID of the created version
        """
        # Generate version ID
        version_id = f"v-{uuid.uuid4().hex[:12]}"
        
        # Create version record
        version = CatalogVersion(
            version_id=version_id,
            catalog=catalog,
            reason=reason
        )
        
        # Verify checksum
        if not version.verify_integrity():
            raise RuntimeError("Failed to compute valid checksum for version")
        
        # Store version
        version_path = f"{self.VERSIONS_PATH}/{version_id}.json"
        self.storage.save_json(version_path, version.to_dict())
        
        # Update index
        self._update_index(version)
        
        # Update cache
        self._version_cache[version_id] = version
        
        # Update current catalog
        self.storage.save_json(self.CATALOG_PATH, catalog)
        
        self._logger.info(
            f"Created version {version_id} with checksum {version.checksum}: {reason}"
        )
        
        return version_id
    
    def _update_index(self, version: CatalogVersion) -> None:
        """
        Update the version index with a new version.
        
        Args:
            version: CatalogVersion to add to index
        """
        # Load existing index
        index = self._load_index()
        
        # Add version entry
        index["versions"].append({
            "version_id": version.version_id,
            "timestamp": version.timestamp,
            "reason": version.reason,
            "checksum": version.checksum,
            "skill_count": len(version.catalog.get("skills", {}))
        })
        
        # Update metadata
        index["total_versions"] = len(index["versions"])
        index["last_updated"] = datetime.utcnow().isoformat() + "Z"
        
        # Save index
        self.storage.save_json(self.INDEX_PATH, index)
        self._index_cache = index
    
    def _load_index(self) -> Dict[str, Any]:
        """
        Load the version index.
        
        Returns:
            Index dictionary
        """
        if self._index_cache:
            return self._index_cache
        
        default_index = {
            "versions": [],
            "total_versions": 0,
            "created": datetime.utcnow().isoformat() + "Z",
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
        
        try:
            loaded = self.storage.load_json(self.INDEX_PATH)
            # Ensure the loaded data has the required structure
            if not isinstance(loaded, dict) or "versions" not in loaded:
                self._index_cache = default_index
            else:
                self._index_cache = loaded
        except Exception:
            self._index_cache = default_index
        
        return self._index_cache
    
    def get_version(self, version_id: str) -> Dict[str, Any]:
        """
        Get a specific version of the catalog.
        
        Args:
            version_id: Version ID to retrieve
            
        Returns:
            Catalog dictionary for the version
            
        Raises:
            ValueError: If version not found
        """
        # Check cache first
        if version_id in self._version_cache:
            return self._version_cache[version_id].catalog
        
        # Load from storage
        version_path = f"{self.VERSIONS_PATH}/{version_id}.json"
        
        try:
            data = self.storage.load_json(version_path)
            version = CatalogVersion.from_dict(data)
            
            # Verify integrity
            if not version.verify_integrity():
                self._logger.warning(
                    f"Version {version_id} checksum mismatch: "
                    f"expected {version.checksum}, got {version._compute_checksum()}"
                )
            
            # Update cache
            self._version_cache[version_id] = version
            
            return version.catalog
            
        except Exception as e:
            raise ValueError(f"Version {version_id} not found: {e}")
    
    def list_versions(self, skill_id: Optional[str] = None) -> List[CatalogVersion]:
        """
        List all versions, optionally filtered by skill.
        
        Args:
            skill_id: Optional skill ID to filter versions by
            
        Returns:
            List of CatalogVersion objects (newest first)
        """
        index = self._load_index()
        versions = []
        
        for entry in reversed(index.get("versions", [])):
            version_id = entry["version_id"]
            
            # Get full version data
            try:
                catalog = self.get_version(version_id)
                
                # Filter by skill if specified
                if skill_id:
                    skills = catalog.get("skills", {})
                    if skill_id not in skills:
                        continue
                
                version = CatalogVersion(
                    version_id=version_id,
                    catalog=catalog,
                    reason=entry.get("reason", ""),
                    timestamp=entry.get("timestamp", ""),
                    checksum=entry.get("checksum", "")
                )
                versions.append(version)
                
            except Exception as e:
                self._logger.warning(f"Failed to load version {version_id}: {e}")
        
        return versions
    
    def rollback_to_version(self, version_id: str) -> Dict[str, Any]:
        """
        Rollback to a specific version of the catalog.
        
        Creates a new version with the catalog from the specified version,
        effectively undoing all changes after that version.
        
        Args:
            version_id: Version ID to rollback to
            
        Returns:
            Catalog dictionary from the rolled-back version
            
        Raises:
            ValueError: If version not found
        """
        # Get the version to rollback to
        catalog = self.get_version(version_id)
        
        # Create a new version for the rollback
        new_version_id = self.create_version(
            catalog=catalog,
            reason=f"Rollback to version {version_id}"
        )
        
        self._logger.info(
            f"Rolled back to version {version_id}, created new version {new_version_id}"
        )
        
        return catalog
    
    def diff_versions(self, v1: str, v2: str) -> CatalogDiff:
        """
        Compare two versions of the catalog.
        
        Args:
            v1: First version ID (source)
            v2: Second version ID (target)
            
        Returns:
            CatalogDiff with the differences
        """
        # Load both versions
        catalog1 = self.get_version(v1)
        catalog2 = self.get_version(v2)
        
        # Get skill lists
        skills1 = set(catalog1.get("skills", {}).keys())
        skills2 = set(catalog2.get("skills", {}).keys())
        
        # Calculate differences
        added = list(skills2 - skills1)
        removed = list(skills1 - skills2)
        
        # Check for modifications in common skills
        modified = {}
        common_skills = skills1 & skills2
        
        for skill_id in common_skills:
            skill1 = catalog1["skills"][skill_id]
            skill2 = catalog2["skills"][skill_id]
            
            # Compare thresholds and other properties
            changes = {}
            
            if skill1.get("threshold") != skill2.get("threshold"):
                changes["threshold"] = {
                    "from": skill1.get("threshold"),
                    "to": skill2.get("threshold")
                }
            
            if changes:
                modified[skill_id] = changes
        
        # Get timestamps
        index = self._load_index()
        timestamp_from = ""
        timestamp_to = ""
        
        for entry in index.get("versions", []):
            if entry["version_id"] == v1:
                timestamp_from = entry.get("timestamp", "")
            elif entry["version_id"] == v2:
                timestamp_to = entry.get("timestamp", "")
        
        return CatalogDiff(
            version_id_from=v1,
            version_id_to=v2,
            added_skills=sorted(added),
            removed_skills=sorted(removed),
            modified_skills=modified,
            timestamp_from=timestamp_from,
            timestamp_to=timestamp_to
        )
    
    def get_version_metadata(self, version_id: str) -> Dict[str, Any]:
        """
        Get metadata for a version without loading the full catalog.
        
        Args:
            version_id: Version ID to get metadata for
            
        Returns:
            Dictionary with version metadata
        """
        index = self._load_index()
        
        for entry in index.get("versions", []):
            if entry["version_id"] == version_id:
                return entry
        
        raise ValueError(f"Version {version_id} not found in index")
    
    def get_latest_version(self) -> Optional[CatalogVersion]:
        """
        Get the most recent version of the catalog.
        
        Returns:
            CatalogVersion or None if no versions exist
        """
        index = self._load_index()
        versions = index.get("versions", [])
        
        if not versions:
            return None
        
        latest = versions[-1]
        
        try:
            catalog = self.get_version(latest["version_id"])
            return CatalogVersion(
                version_id=latest["version_id"],
                catalog=catalog,
                reason=latest.get("reason", ""),
                timestamp=latest.get("timestamp", ""),
                checksum=latest.get("checksum", "")
            )
        except Exception:
            return None
    
    def get_version_count(self) -> int:
        """
        Get the total number of versions.
        
        Returns:
            Number of versions
        """
        index = self._load_index()
        return len(index.get("versions", []))
    
    def prune_old_versions(self, keep_count: int = 10) -> int:
        """
        Remove old versions, keeping only the most recent.
        
        Args:
            keep_count: Number of recent versions to keep
            
        Returns:
            Number of versions removed
        """
        index = self._load_index()
        versions = index.get("versions", [])
        
        if len(versions) <= keep_count:
            return 0
        
        # Identify versions to remove
        to_remove = versions[:-keep_count]
        to_keep = versions[-keep_count:]
        
        removed_count = 0
        
        for entry in to_remove:
            version_id = entry["version_id"]
            version_path = f"{self.VERSIONS_PATH}/{version_id}.json"
            
            try:
                self.storage.delete(version_path)
                removed_count += 1
                
                # Remove from cache
                if version_id in self._version_cache:
                    del self._version_cache[version_id]
                
            except Exception as e:
                self._logger.warning(f"Failed to remove version {version_id}: {e}")
        
        # Update index
        index["versions"] = to_keep
        index["total_versions"] = len(to_keep)
        index["last_updated"] = datetime.utcnow().isoformat() + "Z"
        
        self.storage.save_json(self.INDEX_PATH, index)
        self._index_cache = index
        
        self._logger.info(f"Pruned {removed_count} old versions, keeping {keep_count}")
        
        return removed_count
    
    def verify_version_integrity(self, version_id: str) -> Dict[str, Any]:
        """
        Verify the integrity of a specific version.
        
        Args:
            version_id: Version ID to verify
            
        Returns:
            Dictionary with verification results
        """
        try:
            version_path = f"{self.VERSIONS_PATH}/{version_id}.json"
            data = self.storage.load_json(version_path)
            version = CatalogVersion.from_dict(data)
            
            is_valid = version.verify_integrity()
            
            return {
                "version_id": version_id,
                "valid": is_valid,
                "stored_checksum": version.checksum,
                "computed_checksum": version._compute_checksum(),
                "timestamp": version.timestamp,
                "skill_count": len(version.catalog.get("skills", {}))
            }
            
        except Exception as e:
            return {
                "version_id": version_id,
                "valid": False,
                "error": str(e)
            }
    
    def get_version_history_for_skill(self, skill_id: str) -> List[Dict[str, Any]]:
        """
        Get the version history for a specific skill.
        
        Args:
            skill_id: Skill ID to get history for
            
        Returns:
            List of version entries with threshold changes
        """
        versions = self.list_versions(skill_id)
        history = []
        
        for version in versions:
            skill = version.catalog.get("skills", {}).get(skill_id, {})
            
            history.append({
                "version_id": version.version_id,
                "timestamp": version.timestamp,
                "reason": version.reason,
                "threshold": skill.get("threshold"),
                "checksum": version.checksum
            })
        
        return history
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about version management.
        
        Returns:
            Dictionary with version statistics
        """
        index = self._load_index()
        versions = index.get("versions", [])
        
        return {
            "total_versions": len(versions),
            "first_version": versions[0].get("timestamp") if versions else None,
            "last_version": versions[-1].get("timestamp") if versions else None,
            "cached_versions": len(self._version_cache),
            "versions_path": self.VERSIONS_PATH
        }
