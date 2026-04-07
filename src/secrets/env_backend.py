"""
Environment Variable Backend for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- Uses environment variables for secret storage
- For DEVELOPMENT ONLY - not secure for production
- Simple and requires no external dependencies

WARNING: This backend is NOT secure for production use!
Environment variables can be leaked in logs, process listings,
and crash dumps. Use Keyring or Vault for production.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import os
from typing import Dict, List, Optional
import logging

from .store import SecretStore, SecretNotFoundError, SecretAccessError


class EnvBackend(SecretStore):
    """
    Secret store using environment variables.
    
    WARNING: NOT SECURE FOR PRODUCTION!
    
    This backend is designed for development and testing only.
    It reads secrets from environment variables with a configurable prefix.
    
    Security concerns:
    - Environment variables visible in process listings
    - May be logged in crash dumps
    - Can leak via error messages
    - Not encrypted at rest
    
    Configuration:
        secrets:
          backend: env
          prefix: TITAN_SECRET_
    
    Usage:
        # Set environment variable
        export TITAN_SECRET_api_key="my-secret-key"
        
        # Use in code
        store = EnvBackend(prefix='TITAN_SECRET_')
        value = store.get('api_key')
    """
    
    DEFAULT_PREFIX = "TITAN_SECRET_"
    
    def __init__(self, config: Dict = None, prefix: str = None):
        """
        Initialize environment backend.
        
        Args:
            config: Configuration dictionary
            prefix: Environment variable prefix (default: TITAN_SECRET_)
        """
        super().__init__(config)
        
        self.prefix = prefix or config.get('prefix', self.DEFAULT_PREFIX)
        
        self._logger.warning(
            "EnvBackend is NOT secure for production use! "
            "Use KeyringBackend or VaultBackend for production."
        )
    
    def _get_env_key(self, key: str) -> str:
        """Convert key to environment variable name."""
        # Replace special characters
        env_key = key.upper().replace('-', '_').replace('.', '_').replace('/', '_')
        return f"{self.prefix}{env_key}"
    
    def get(self, key: str) -> str:
        """
        Retrieve a secret from environment variables.
        
        Args:
            key: Secret key
            
        Returns:
            Secret value
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
        """
        env_key = self._get_env_key(key)
        value = os.environ.get(env_key)
        
        if value is None:
            raise SecretNotFoundError(key)
        
        return value
    
    def set(self, key: str, value: str, metadata: Dict = None) -> None:
        """
        Set a secret in environment variables.
        
        Note: This only sets for the current process.
        
        Args:
            key: Secret key
            value: Secret value
            metadata: Ignored
        """
        env_key = self._get_env_key(key)
        os.environ[env_key] = value
        self._logger.debug(f"Set environment variable: {env_key}")
    
    def delete(self, key: str) -> None:
        """
        Delete a secret from environment variables.
        
        Args:
            key: Secret key
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
        """
        env_key = self._get_env_key(key)
        
        if env_key not in os.environ:
            raise SecretNotFoundError(key)
        
        del os.environ[env_key]
        self._logger.debug(f"Deleted environment variable: {env_key}")
    
    def exists(self, key: str) -> bool:
        """
        Check if a secret exists.
        
        Args:
            key: Secret key
            
        Returns:
            True if secret exists
        """
        env_key = self._get_env_key(key)
        return env_key in os.environ
    
    def list_keys(self, prefix: str = None) -> List[str]:
        """
        List all secret keys.
        
        Args:
            prefix: Optional prefix to filter keys
            
        Returns:
            List of secret keys
        """
        keys = []
        
        for env_key in os.environ:
            if env_key.startswith(self.prefix):
                # Remove prefix to get the original key
                key = env_key[len(self.prefix):]
                # Convert back to lowercase
                key = key.lower().replace('_', '-')
                
                if prefix is None or key.startswith(prefix):
                    keys.append(key)
        
        return sorted(keys)
    
    def health_check(self) -> Dict:
        """Check backend health."""
        result = super().health_check()
        
        count = len(self.list_keys())
        result['secret_count'] = count
        result['prefix'] = self.prefix
        result['warning'] = "NOT SECURE FOR PRODUCTION - environment variables can leak"
        result['message'] = f"EnvBackend operational with {count} secrets"
        
        return result
    
    def load_from_file(self, file_path: str) -> int:
        """
        Load secrets from a .env file.
        
        Args:
            file_path: Path to .env file
            
        Returns:
            Number of secrets loaded
        """
        loaded = 0
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse KEY=VALUE
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        
                        # Set in environment (without prefix, as file should have full keys)
                        if key.startswith(self.prefix):
                            os.environ[key] = value
                            loaded += 1
                        else:
                            # Add prefix if not present
                            self.set(key.lower().replace('_', '-'), value)
                            loaded += 1
            
            self._logger.info(f"Loaded {loaded} secrets from {file_path}")
            
        except Exception as e:
            self._logger.error(f"Failed to load secrets from file: {e}")
        
        return loaded
    
    def load_from_dict(self, secrets: Dict[str, str]) -> int:
        """
        Load secrets from a dictionary.
        
        Args:
            secrets: Dictionary of key-value pairs
            
        Returns:
            Number of secrets loaded
        """
        for key, value in secrets.items():
            self.set(key, str(value))
        
        return len(secrets)
