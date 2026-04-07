"""
Secret Store Base Class for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- Abstract base class for secret storage backends
- Common interface for all backends
- Error handling and logging

Author: TITAN FUSE Team
Version: 3.3.0
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging


class SecretStoreError(Exception):
    """Base exception for secret store errors."""
    pass


class SecretNotFoundError(SecretStoreError):
    """Raised when a secret is not found."""
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Secret not found: {key}")


class SecretAccessError(SecretStoreError):
    """Raised when there's an error accessing the secret store."""
    pass


@dataclass
class SecretMetadata:
    """Metadata about a stored secret."""
    key: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    version: Optional[int] = None
    labels: Optional[Dict[str, str]] = None
    
    def to_dict(self) -> Dict:
        return {
            'key': self.key,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'version': self.version,
            'labels': self.labels
        }


class SecretStore(ABC):
    """
    Abstract base class for secret storage backends.
    
    Provides a unified interface for storing and retrieving secrets
    across different backends (keyring, Vault, environment variables).
    
    INVARIANTS:
    - ADAPTER_ISOLATION: Each backend is isolated from others
    - NO_FABRICATION: Secrets are never fabricated, only stored/retrieved
    - Credentials never appear in checkpoint.json or session state
    
    Usage:
        store = get_secret_store()  # Factory creates appropriate backend
        store.set('api_key', 'secret-value')
        value = store.get('api_key')
        store.delete('api_key')
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize secret store.
        
        Args:
            config: Backend-specific configuration
        """
        self.config = config or {}
        self._logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    def get(self, key: str) -> str:
        """
        Retrieve a secret value.
        
        Args:
            key: Secret key/identifier
            
        Returns:
            Secret value as string
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            SecretAccessError: If there's an error accessing the store
        """
        pass
    
    @abstractmethod
    def set(self, key: str, value: str, metadata: Dict = None) -> None:
        """
        Store a secret value.
        
        Args:
            key: Secret key/identifier
            value: Secret value to store
            metadata: Optional metadata (backend-specific)
            
        Raises:
            SecretAccessError: If there's an error storing the secret
        """
        pass
    
    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Delete a secret.
        
        Args:
            key: Secret key/identifier
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            SecretAccessError: If there's an error deleting the secret
        """
        pass
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if a secret exists.
        
        Args:
            key: Secret key/identifier
            
        Returns:
            True if secret exists, False otherwise
        """
        pass
    
    @abstractmethod
    def list_keys(self, prefix: str = None) -> List[str]:
        """
        List all secret keys.
        
        Args:
            prefix: Optional prefix to filter keys
            
        Returns:
            List of secret keys
        """
        pass
    
    def get_or_default(self, key: str, default: str = None) -> Optional[str]:
        """
        Get a secret or return default if not found.
        
        Args:
            key: Secret key/identifier
            default: Default value if not found
            
        Returns:
            Secret value or default
        """
        try:
            return self.get(key)
        except SecretNotFoundError:
            return default
    
    def get_metadata(self, key: str) -> Optional[SecretMetadata]:
        """
        Get metadata about a secret (if supported).
        
        Args:
            key: Secret key/identifier
            
        Returns:
            SecretMetadata or None if not supported
        """
        return None
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check if the secret store is healthy.
        
        Returns:
            Dict with 'healthy' boolean and 'message' string
        """
        try:
            # Try to list keys as a basic health check
            self.list_keys()
            return {
                'healthy': True,
                'backend': self.__class__.__name__,
                'message': 'Secret store is operational'
            }
        except Exception as e:
            return {
                'healthy': False,
                'backend': self.__class__.__name__,
                'message': str(e)
            }
    
    def create_secret_ref(self, key: str) -> str:
        """
        Create a secret reference string for use in state.
        
        Instead of storing credentials in state, store references.
        Format: "secret_ref:key"
        
        Args:
            key: Secret key/identifier
            
        Returns:
            Secret reference string
        """
        return f"secret_ref:{key}"
    
    def resolve_secret_ref(self, ref: str) -> str:
        """
        Resolve a secret reference to its actual value.
        
        Args:
            ref: Secret reference string (format: "secret_ref:key")
            
        Returns:
            Secret value
            
        Raises:
            ValueError: If ref is not a valid secret reference
            SecretNotFoundError: If referenced secret doesn't exist
        """
        if not ref.startswith("secret_ref:"):
            raise ValueError(f"Invalid secret reference: {ref}")
        
        key = ref[len("secret_ref:"):]
        return self.get(key)
    
    def is_secret_ref(self, value: str) -> bool:
        """
        Check if a value is a secret reference.
        
        Args:
            value: Value to check
            
        Returns:
            True if value is a secret reference
        """
        return isinstance(value, str) and value.startswith("secret_ref:")
    
    def scan_for_secrets(self, data: Dict) -> List[str]:
        """
        Scan a dictionary for potential secret patterns.
        
        Args:
            data: Dictionary to scan
            
        Returns:
            List of keys that might contain secrets
        """
        import re
        
        secret_patterns = [
            r'api[_-]?key',
            r'secret[_-]?key',
            r'access[_-]?token',
            r'auth[_-]?token',
            r'password',
            r'credential',
            r'private[_-]?key',
        ]
        
        findings = []
        
        def scan_dict(d: Dict, path: str = ""):
            for key, value in d.items():
                current_path = f"{path}.{key}" if path else key
                
                # Check key name
                for pattern in secret_patterns:
                    if re.search(pattern, key, re.IGNORECASE):
                        findings.append(current_path)
                        break
                
                # Recurse into nested dicts
                if isinstance(value, dict):
                    scan_dict(value, current_path)
        
        scan_dict(data)
        return findings
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
