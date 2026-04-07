"""
Secret Store Factory for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- Factory functions for creating secret stores
- Configuration-driven backend selection
- Fallback to safe defaults

Author: TITAN FUSE Team
Version: 3.3.0
"""

from typing import Dict, Optional, Any
import logging

from .store import SecretStore, SecretStoreError

# Backend availability flags and classes
try:
    from .keyring_backend import KeyringBackend
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    KeyringBackend = None

try:
    from .vault_backend import VaultBackend
    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False
    VaultBackend = None

try:
    from .env_backend import EnvBackend
    ENV_AVAILABLE = True
except ImportError:
    ENV_AVAILABLE = False
    EnvBackend = None


logger = logging.getLogger(__name__)


def get_secret_store(config: Dict = None) -> SecretStore:
    """
    Get a secret store instance based on configuration.
    
    This is the main factory function for creating secret stores.
    It selects the appropriate backend based on configuration.
    
    Configuration:
        secrets:
          backend: keyring | vault | env
          # Backend-specific options...
    
    Args:
        config: Configuration dictionary with 'secrets' section
        
    Returns:
        SecretStore instance
        
    Raises:
        SecretStoreError: If no backend is available
    """
    config = config or {}
    secrets_config = config.get('secrets', {})
    
    backend = secrets_config.get('backend', 'env')  # Default to env for safety
    
    return create_secret_store(backend, secrets_config)


def create_secret_store(backend: str, config: Dict = None) -> SecretStore:
    """
    Create a specific secret store backend.
    
    Args:
        backend: Backend name ('keyring', 'vault', 'env')
        config: Backend-specific configuration
        
    Returns:
        SecretStore instance
        
    Raises:
        SecretStoreError: If backend is not available or invalid
    """
    config = config or {}
    
    if backend == 'keyring':
        if not KEYRING_AVAILABLE:
            raise SecretStoreError(
                "Keyring backend not available. Install with: pip install keyring"
            )
        return KeyringBackend(config)
    
    elif backend == 'vault':
        if not VAULT_AVAILABLE:
            raise SecretStoreError(
                "Vault backend not available. Install with: pip install hvac"
            )
        return VaultBackend(config)
    
    elif backend == 'env':
        if not ENV_AVAILABLE:
            raise SecretStoreError(
                "Env backend not available (should always be available)"
            )
        return EnvBackend(config)
    
    else:
        raise SecretStoreError(f"Unknown secret store backend: {backend}")


def get_available_backends() -> Dict[str, bool]:
    """
    Get list of available backends.
    
    Returns:
        Dict mapping backend names to availability
    """
    return {
        'keyring': KEYRING_AVAILABLE,
        'vault': VAULT_AVAILABLE,
        'env': ENV_AVAILABLE
    }


def health_check_all(config: Dict = None) -> Dict[str, Dict]:
    """
    Run health check on all available backends.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Dict mapping backend names to health check results
    """
    results = {}
    
    for backend_name, available in get_available_backends().items():
        if not available:
            results[backend_name] = {
                'available': False,
                'healthy': False,
                'message': 'Backend not installed'
            }
            continue
        
        try:
            store = create_secret_store(backend_name, config)
            health = store.health_check()
            health['available'] = True
            results[backend_name] = health
        except Exception as e:
            results[backend_name] = {
                'available': True,
                'healthy': False,
                'message': str(e)
            }
    
    return results


def recommend_backend() -> str:
    """
    Recommend the best available backend.
    
    Priority:
    1. Vault (if configured) - enterprise security
    2. Keyring - OS-level security
    3. Env - development only
    
    Returns:
        Recommended backend name
    """
    import os
    
    # Check for Vault configuration
    if os.environ.get('VAULT_ADDR') and os.environ.get('VAULT_TOKEN'):
        if VAULT_AVAILABLE:
            return 'vault'
    
    # Check for keyring
    if KEYRING_AVAILABLE:
        try:
            # Quick test
            import keyring
            backend = keyring.get_keyring()
            if backend and hasattr(backend, 'name'):
                return 'keyring'
        except:
            pass
    
    # Fallback to env
    return 'env'


class SecretStoreManager:
    """
    Manager for secret store instances.
    
    Provides singleton access to secret stores and
    manages multiple backends.
    """
    
    _instance: Optional['SecretStoreManager'] = None
    _stores: Dict[str, SecretStore] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_store(self, backend: str = None, config: Dict = None) -> SecretStore:
        """
        Get or create a secret store.
        
        Args:
            backend: Backend name (uses default if not specified)
            config: Configuration dictionary
            
        Returns:
            SecretStore instance
        """
        config = config or {}
        
        if backend is None:
            backend = config.get('secrets', {}).get('backend', recommend_backend())
        
        cache_key = f"{backend}:{id(config)}"
        
        if cache_key not in self._stores:
            self._stores[cache_key] = create_secret_store(backend, config)
        
        return self._stores[cache_key]
    
    def clear_cache(self) -> None:
        """Clear cached store instances."""
        self._stores.clear()
    
    @classmethod
    def get_instance(cls) -> 'SecretStoreManager':
        """Get singleton instance."""
        return cls()


# Convenience function for quick access
def get_secret(key: str, config: Dict = None) -> str:
    """
    Quick access to a secret value.
    
    Args:
        key: Secret key
        config: Optional configuration
        
    Returns:
        Secret value
        
    Raises:
        SecretNotFoundError: If secret not found
    """
    store = get_secret_store(config)
    return store.get(key)


def set_secret(key: str, value: str, config: Dict = None) -> None:
    """
    Quick access to set a secret value.
    
    Args:
        key: Secret key
        value: Secret value
        config: Optional configuration
    """
    store = get_secret_store(config)
    store.set(key, value)
