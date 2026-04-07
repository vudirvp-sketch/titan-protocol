"""
HashiCorp Vault Backend for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- Uses HashiCorp Vault for secret storage
- Enterprise-grade secret management
- Support for KV secrets engine
- Token and AppRole authentication

Author: TITAN FUSE Team
Version: 3.3.0
"""

from typing import Dict, List, Optional
import os
import logging

try:
    import hvac
    VAULT_INSTALLED = True
except ImportError:
    VAULT_INSTALLED = False
    hvac = None

from .store import SecretStore, SecretNotFoundError, SecretAccessError, SecretMetadata


class VaultBackend(SecretStore):
    """
    Secret store using HashiCorp Vault.
    
    Provides enterprise-grade secret management with:
    - Centralized secret storage
    - Audit logging
    - Secret versioning
    - Dynamic secrets
    - Lease management
    
    Requirements:
        pip install hvac
        Running Vault server
    
    Configuration:
        vault:
          url: "http://localhost:8200"
          token: "your-token"  # Or use VAULT_TOKEN env
          namespace: ""  # Optional Vault namespace
          mount_point: "secret"  # KV engine mount point
          auth_method: "token"  # token, approle, or kubernetes
    
    Usage:
        store = VaultBackend({
            'url': 'http://localhost:8200',
            'token': 'your-token'
        })
        store.set('api_key', 'secret-value')
        value = store.get('api_key')
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Vault backend.
        
        Args:
            config: Configuration dictionary with keys:
                - url: Vault server URL
                - token: Vault token (or use VAULT_TOKEN env)
                - namespace: Vault namespace (optional)
                - mount_point: KV engine mount point (default: secret)
                - auth_method: Authentication method
        """
        super().__init__(config)
        
        if not VAULT_INSTALLED:
            raise ImportError(
                "hvac package not installed. Install with: pip install hvac"
            )
        
        self.url = config.get('url', os.environ.get('VAULT_ADDR', 'http://localhost:8200'))
        self.token = config.get('token', os.environ.get('VAULT_TOKEN'))
        self.namespace = config.get('namespace', os.environ.get('VAULT_NAMESPACE'))
        self.mount_point = config.get('mount_point', 'secret')
        self.path_prefix = config.get('path_prefix', 'titan')
        
        # Initialize client
        self._client = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize Vault client with authentication."""
        try:
            self._client = hvac.Client(
                url=self.url,
                token=self.token,
                namespace=self.namespace
            )
            
            # Verify connection
            if not self._client.is_authenticated():
                raise SecretAccessError(
                    "Vault authentication failed. Check token or auth configuration."
                )
            
            self._logger.info(f"Connected to Vault at {self.url}")
            
        except Exception as e:
            self._logger.error(f"Failed to connect to Vault: {e}")
            raise SecretAccessError(f"Vault connection failed: {e}")
    
    def _get_secret_path(self, key: str) -> str:
        """Get full secret path."""
        return f"{self.path_prefix}/{key}"
    
    def get(self, key: str) -> str:
        """
        Retrieve a secret from Vault.
        
        Args:
            key: Secret key
            
        Returns:
            Secret value
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            SecretAccessError: If Vault access fails
        """
        try:
            secret_path = self._get_secret_path(key)
            
            # Read from KV v2
            response = self._client.secrets.kv.v2.read_secret_version(
                path=secret_path,
                mount_point=self.mount_point
            )
            
            data = response.get('data', {}).get('data', {})
            
            # Return the 'value' field
            if 'value' in data:
                return data['value']
            elif len(data) == 1:
                # Single field, return its value
                return list(data.values())[0]
            else:
                # Multiple fields, return as JSON
                import json
                return json.dumps(data)
                
        except hvac.exceptions.InvalidPath:
            raise SecretNotFoundError(key)
        except Exception as e:
            self._logger.error(f"Vault read error for {key}: {e}")
            raise SecretAccessError(f"Failed to read from Vault: {e}")
    
    def set(self, key: str, value: str, metadata: Dict = None) -> None:
        """
        Store a secret in Vault.
        
        Args:
            key: Secret key
            value: Secret value
            metadata: Optional metadata to store with secret
        """
        try:
            secret_path = self._get_secret_path(key)
            
            secret_data = {
                'value': value,
                'metadata': metadata or {}
            }
            
            # Write to KV v2
            self._client.secrets.kv.v2.create_or_update_secret(
                path=secret_path,
                secret=secret_data,
                mount_point=self.mount_point
            )
            
            self._logger.debug(f"Stored secret in Vault: {key}")
            
        except Exception as e:
            self._logger.error(f"Vault write error for {key}: {e}")
            raise SecretAccessError(f"Failed to write to Vault: {e}")
    
    def delete(self, key: str) -> None:
        """
        Delete a secret from Vault.
        
        Args:
            key: Secret key
        """
        try:
            secret_path = self._get_secret_path(key)
            
            # Delete from KV v2 (marks as deleted, metadata preserved)
            self._client.secrets.kv.v2.delete_latest_version_of_secret(
                path=secret_path,
                mount_point=self.mount_point
            )
            
            self._logger.debug(f"Deleted secret from Vault: {key}")
            
        except hvac.exceptions.InvalidPath:
            raise SecretNotFoundError(key)
        except Exception as e:
            self._logger.error(f"Vault delete error for {key}: {e}")
            raise SecretAccessError(f"Failed to delete from Vault: {e}")
    
    def exists(self, key: str) -> bool:
        """Check if secret exists in Vault."""
        try:
            secret_path = self._get_secret_path(key)
            self._client.secrets.kv.v2.read_secret_metadata(
                path=secret_path,
                mount_point=self.mount_point
            )
            return True
        except hvac.exceptions.InvalidPath:
            return False
        except:
            return False
    
    def list_keys(self, prefix: str = None) -> List[str]:
        """
        List secrets in Vault.
        
        Args:
            prefix: Optional prefix to filter keys
            
        Returns:
            List of secret keys
        """
        try:
            path = self.path_prefix
            if prefix:
                path = f"{path}/{prefix}"
            
            response = self._client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point=self.mount_point
            )
            
            keys = response.get('data', {}).get('keys', [])
            
            # Remove path prefix from keys
            result = []
            for key in keys:
                if key.endswith('/'):
                    # It's a directory, recurse
                    subkeys = self.list_keys(key.rstrip('/'))
                    result.extend(subkeys)
                else:
                    result.append(key)
            
            return result
            
        except hvac.exceptions.InvalidPath:
            return []
        except Exception as e:
            self._logger.error(f"Vault list error: {e}")
            return []
    
    def get_metadata(self, key: str) -> Optional[SecretMetadata]:
        """Get secret metadata from Vault."""
        try:
            secret_path = self._get_secret_path(key)
            
            response = self._client.secrets.kv.v2.read_secret_metadata(
                path=secret_path,
                mount_point=self.mount_point
            )
            
            metadata = response.get('data', {})
            
            return SecretMetadata(
                key=key,
                created_at=metadata.get('created_time'),
                updated_at=metadata.get('updated_time'),
                version=metadata.get('current_version'),
                labels=metadata.get('custom_metadata')
            )
            
        except:
            return None
    
    def health_check(self) -> Dict:
        """Check Vault health."""
        result = super().health_check()
        
        try:
            health = self._client.sys.read_health_status()
            result['vault_healthy'] = True
            result['vault_initialized'] = getattr(health, 'initialized', True)
            result['vault_sealed'] = getattr(health, 'sealed', False)
            
            if getattr(health, 'sealed', False):
                result['healthy'] = False
                result['message'] = "Vault is sealed"
            else:
                result['message'] = "Vault is healthy and unsealed"
                
        except Exception as e:
            result['healthy'] = False
            result['message'] = f"Vault health check failed: {e}"
        
        return result
