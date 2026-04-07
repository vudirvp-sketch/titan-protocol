"""
Keyring Backend for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- Uses system keyring for secret storage
- Cross-platform support (OSX Keychain, Windows Credential Manager, Linux Secret Service)
- Secure storage using OS-level encryption

Author: TITAN FUSE Team
Version: 3.3.0
"""

from typing import Dict, List, Optional
import logging

try:
    import keyring
    from keyring.errors import KeyringError, NoKeyringError
    KEYRING_INSTALLED = True
except ImportError:
    KEYRING_INSTALLED = False
    KeyringError = Exception
    NoKeyringError = Exception

from .store import SecretStore, SecretNotFoundError, SecretAccessError, SecretMetadata


class KeyringBackend(SecretStore):
    """
    Secret store using system keyring.
    
    Uses the 'keyring' Python package to store secrets in the
    operating system's credential storage:
    - macOS: Keychain
    - Windows: Credential Manager
    - Linux: Secret Service (GNOME Keyring, KWallet)
    
    Security Features:
    - OS-level encryption
    - Integration with user login
    - Automatic locking when user logs out
    
    Requirements:
        pip install keyring
    
    Usage:
        store = KeyringBackend(service_name='titan-protocol')
        store.set('api_key', 'secret-value')
        value = store.get('api_key')
    """
    
    SERVICE_NAME = "titan-protocol"
    
    def __init__(self, config: Dict = None, service_name: str = None):
        """
        Initialize keyring backend.
        
        Args:
            config: Configuration dictionary
            service_name: Service name for keyring (default: 'titan-protocol')
        """
        super().__init__(config)
        
        if not KEYRING_INSTALLED:
            raise ImportError(
                "keyring package not installed. Install with: pip install keyring"
            )
        
        self.service_name = service_name or config.get('service_name', self.SERVICE_NAME)
        
        # Verify keyring is available
        try:
            # Check if a keyring backend is available
            backend = keyring.get_keyring()
            self._logger.info(f"Keyring backend: {backend.name}")
        except NoKeyringError:
            raise SecretAccessError(
                "No keyring backend available. "
                "On Linux, ensure gnome-keyring or kwallet is running. "
                "On macOS/Windows, the native keychain should work."
            )
    
    def get(self, key: str) -> str:
        """
        Retrieve a secret from keyring.
        
        Args:
            key: Secret key
            
        Returns:
            Secret value
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            SecretAccessError: If keyring access fails
        """
        try:
            value = keyring.get_password(self.service_name, key)
            
            if value is None:
                raise SecretNotFoundError(key)
            
            return value
            
        except KeyringError as e:
            self._logger.error(f"Keyring access error for {key}: {e}")
            raise SecretAccessError(f"Failed to access keyring: {e}")
    
    def set(self, key: str, value: str, metadata: Dict = None) -> None:
        """
        Store a secret in keyring.
        
        Args:
            key: Secret key
            value: Secret value
            metadata: Ignored (keyring doesn't support metadata)
            
        Raises:
            SecretAccessError: If keyring access fails
        """
        try:
            keyring.set_password(self.service_name, key, value)
            self._logger.debug(f"Stored secret: {key}")
            
        except KeyringError as e:
            self._logger.error(f"Failed to store secret {key}: {e}")
            raise SecretAccessError(f"Failed to store secret: {e}")
    
    def delete(self, key: str) -> None:
        """
        Delete a secret from keyring.
        
        Args:
            key: Secret key
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            SecretAccessError: If keyring access fails
        """
        try:
            # Check if exists first
            if not self.exists(key):
                raise SecretNotFoundError(key)
            
            keyring.delete_password(self.service_name, key)
            self._logger.debug(f"Deleted secret: {key}")
            
        except KeyringError as e:
            self._logger.error(f"Failed to delete secret {key}: {e}")
            raise SecretAccessError(f"Failed to delete secret: {e}")
    
    def exists(self, key: str) -> bool:
        """
        Check if a secret exists.
        
        Args:
            key: Secret key
            
        Returns:
            True if secret exists
        """
        try:
            value = keyring.get_password(self.service_name, key)
            return value is not None
        except KeyringError:
            return False
    
    def list_keys(self, prefix: str = None) -> List[str]:
        """
        List all secret keys.
        
        Note: Keyring doesn't natively support listing keys.
        This implementation maintains a separate registry.
        
        Args:
            prefix: Optional prefix to filter keys
            
        Returns:
            List of known keys
        """
        # Keyring doesn't have a native list function
        # We maintain a registry key
        registry_key = "_key_registry"
        
        try:
            registry_value = keyring.get_password(self.service_name, registry_key)
            if registry_value:
                keys = registry_value.split(',')
                if prefix:
                    keys = [k for k in keys if k.startswith(prefix)]
                return keys
        except KeyringError:
            pass
        
        return []
    
    def _register_key(self, key: str) -> None:
        """Register a key in the registry."""
        if key.startswith('_'):
            return  # Don't register internal keys
            
        registry_key = "_key_registry"
        existing = self.list_keys()
        
        if key not in existing:
            existing.append(key)
            try:
                keyring.set_password(
                    self.service_name, 
                    registry_key, 
                    ','.join(existing)
                )
            except KeyringError:
                pass  # Best effort
    
    def health_check(self) -> Dict:
        """
        Check keyring health.
        
        Returns:
            Health check result
        """
        result = super().health_check()
        
        try:
            # Try a test write/read/delete
            test_key = "_health_check_test"
            test_value = "test_value_123"
            
            keyring.set_password(self.service_name, test_key, test_value)
            retrieved = keyring.get_password(self.service_name, test_key)
            keyring.delete_password(self.service_name, test_key)
            
            if retrieved != test_value:
                result['healthy'] = False
                result['message'] = "Keyring read/write test failed"
            else:
                result['message'] = "Keyring is operational (read/write verified)"
                
        except Exception as e:
            result['healthy'] = False
            result['message'] = f"Keyring health check failed: {e}"
        
        return result
