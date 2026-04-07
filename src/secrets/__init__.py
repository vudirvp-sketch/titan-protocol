"""
Secret Store Module for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- SecretStore abstract base class
- Multiple backend implementations (Keyring, Vault, Env)
- Secure credential storage
- Checkpoint encryption support

This module provides a secure way to store and retrieve secrets,
preventing credential leaks in checkpoints and session state.

Author: TITAN FUSE Team
Version: 3.3.0
"""

from .store import SecretStore, SecretNotFoundError, SecretStoreError
from .factory import get_secret_store, create_secret_store

# Optional backends
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

try:
    from .checkpoint_crypto import CheckpointCrypto
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    CheckpointCrypto = None


__all__ = [
    # Base
    'SecretStore',
    'SecretNotFoundError',
    'SecretStoreError',
    
    # Factory
    'get_secret_store',
    'create_secret_store',
    
    # Backends
    'KeyringBackend',
    'VaultBackend', 
    'EnvBackend',
    
    # Availability flags
    'KEYRING_AVAILABLE',
    'VAULT_AVAILABLE',
    'ENV_AVAILABLE',
    
    # Crypto
    'CheckpointCrypto',
    'CRYPTO_AVAILABLE'
]
