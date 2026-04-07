"""
Safe checkpoint serialization module for TITAN FUSE Protocol.

ITEM-073 Implementation:
- SerializationFormat enum (JSON_ZSTD, JSON, PICKLE_UNSAFE)
- serialize_checkpoint() with safe default
- deserialize_checkpoint() with format detection
- Safety gate: PICKLE_UNSAFE requires --unsafe CLI flag
- Zstd compression for production use

ITEM-STOR-01 Integration:
- StorageBackend integration for cloud storage
- serialize_checkpoint_to_storage() using StorageBackend
- deserialize_checkpoint_from_storage() using StorageBackend

Default: JSON + zstd compression (safe, recommended)
Fast mode: pickle with --unsafe flag (not recommended for untrusted sources)

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import gzip
import pickle
import hashlib
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from enum import Enum
import logging

try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False


class SerializationFormat(Enum):
    """
    Supported checkpoint serialization formats.
    
    Safety ranking:
    - JSON_ZSTD: Safe, compressed, recommended for production
    - JSON: Safe, uncompressed, good for debugging
    - PICKLE_UNSAFE: UNSAFE - only use with --unsafe flag and trusted sources
    """
    JSON_ZSTD = "json_zstd"
    JSON = "json"
    PICKLE_UNSAFE = "pickle_unsafe"
    
    @classmethod
    def from_string(cls, value: str) -> 'SerializationFormat':
        """Parse format from config string."""
        mapping = {
            'json_zstd': cls.JSON_ZSTD,
            'json': cls.JSON,
            'pickle': cls.PICKLE_UNSAFE,
            'pickle_unsafe': cls.PICKLE_UNSAFE,
            'gzip': cls.JSON,  # Fallback to JSON for gzip
            'none': cls.JSON,
        }
        return mapping.get(value.lower(), cls.JSON_ZSTD)
    
    @property
    def is_safe(self) -> bool:
        """Check if format is safe for untrusted sources."""
        return self != SerializationFormat.PICKLE_UNSAFE
    
    @property
    def file_extension(self) -> str:
        """Get file extension for format."""
        extensions = {
            SerializationFormat.JSON_ZSTD: '.json.zst',
            SerializationFormat.JSON: '.json',
            SerializationFormat.PICKLE_UNSAFE: '.pkl',
        }
        return extensions[self]


class SerializationResult:
    """Result of checkpoint serialization."""
    
    def __init__(self, success: bool, path: Path = None, format: SerializationFormat = None,
                 size_bytes: int = 0, checksum: str = None, error: str = None,
                 compression_ratio: float = 1.0):
        self.success = success
        self.path = path
        self.format = format
        self.size_bytes = size_bytes
        self.checksum = checksum
        self.error = error
        self.compression_ratio = compression_ratio
    
    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'path': str(self.path) if self.path else None,
            'format': self.format.value if self.format else None,
            'size_bytes': self.size_bytes,
            'checksum': self.checksum,
            'error': self.error,
            'compression_ratio': self.compression_ratio
        }


def serialize_checkpoint(data: Dict, path: Path = None, 
                        format: SerializationFormat = SerializationFormat.JSON_ZSTD,
                        unsafe_mode: bool = False) -> SerializationResult:
    """
    Serialize checkpoint data to file.
    
    Default format is JSON_ZSTD (safe, compressed).
    PICKLE_UNSAFE format requires unsafe_mode=True (--unsafe flag).
    
    Args:
        data: Checkpoint data dictionary
        path: Output file path (auto-generated if not provided)
        format: Serialization format (default: JSON_ZSTD)
        unsafe_mode: Set True to allow PICKLE_UNSAFE format
        
    Returns:
        SerializationResult with success status and metadata
        
    Raises:
        ValueError: If PICKLE_UNSAFE requested without unsafe_mode
    """
    logger = logging.getLogger(__name__)
    
    # Safety gate for pickle format (ITEM-073 step 05)
    if format == SerializationFormat.PICKLE_UNSAFE and not unsafe_mode:
        error_msg = (
            "[gap: unsafe_serialization_requires_explicit_flag] "
            "PICKLE_UNSAFE format requires --unsafe CLI flag. "
            "Use JSON_ZSTD (default) or JSON for safe serialization."
        )
        logger.error(error_msg)
        return SerializationResult(
            success=False,
            format=format,
            error=error_msg
        )
    
    # Add metadata
    data['_serialization'] = {
        'format': format.value,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'safe': format.is_safe
    }
    
    try:
        if format == SerializationFormat.JSON_ZSTD:
            return _serialize_json_zstd(data, path)
        elif format == SerializationFormat.JSON:
            return _serialize_json(data, path)
        elif format == SerializationFormat.PICKLE_UNSAFE:
            return _serialize_pickle(data, path)
        else:
            return SerializationResult(
                success=False,
                format=format,
                error=f"Unsupported format: {format}"
            )
    except Exception as e:
        logger.error(f"Serialization failed: {e}")
        return SerializationResult(
            success=False,
            format=format,
            error=str(e)
        )


def _serialize_json_zstd(data: Dict, path: Path) -> SerializationResult:
    """Serialize to JSON with Zstd compression."""
    if not ZSTD_AVAILABLE:
        # Fallback to gzip
        return _serialize_gzip(data, path)
    
    json_bytes = json.dumps(data, default=str, indent=2).encode('utf-8')
    original_size = len(json_bytes)
    
    cctx = zstd.ZstdCompressor(level=3)
    compressed = cctx.compress(json_bytes)
    
    if path:
        path = path.with_suffix('.json.zst')
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(compressed)
    else:
        path = Path('checkpoint.json.zst')
    
    checksum = hashlib.sha256(compressed).hexdigest()[:16]
    
    return SerializationResult(
        success=True,
        path=path,
        format=SerializationFormat.JSON_ZSTD,
        size_bytes=len(compressed),
        checksum=checksum,
        compression_ratio=len(compressed) / original_size if original_size > 0 else 1.0
    )


def _serialize_json(data: Dict, path: Path) -> SerializationResult:
    """Serialize to plain JSON."""
    json_str = json.dumps(data, default=str, indent=2)
    json_bytes = json_str.encode('utf-8')
    
    if path:
        path = path.with_suffix('.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            f.write(json_str)
    else:
        path = Path('checkpoint.json')
    
    checksum = hashlib.sha256(json_bytes).hexdigest()[:16]
    
    return SerializationResult(
        success=True,
        path=path,
        format=SerializationFormat.JSON,
        size_bytes=len(json_bytes),
        checksum=checksum,
        compression_ratio=1.0
    )


def _serialize_gzip(data: Dict, path: Path) -> SerializationResult:
    """Serialize to gzipped JSON (fallback when zstd unavailable)."""
    json_bytes = json.dumps(data, default=str, indent=2).encode('utf-8')
    original_size = len(json_bytes)
    
    if path:
        # Replace any existing extension with .json.gz
        # Handle double extensions like .json.zst
        stem = path.stem
        if stem.endswith('.json'):
            stem = stem[:-5]  # Remove .json from stem
        path = path.parent / f"{stem}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, 'wt') as f:
            json.dump(data, f, default=str, indent=2)
    else:
        path = Path('checkpoint.json.gz')
        with gzip.open(path, 'wt') as f:
            json.dump(data, f, default=str, indent=2)
    
    compressed_size = path.stat().st_size if path.exists() else 0
    checksum = hashlib.sha256(json_bytes).hexdigest()[:16]
    
    return SerializationResult(
        success=True,
        path=path,
        format=SerializationFormat.JSON,  # Treat as JSON variant
        size_bytes=compressed_size,
        checksum=checksum,
        compression_ratio=compressed_size / original_size if original_size > 0 else 1.0
    )


def _serialize_pickle(data: Dict, path: Path) -> SerializationResult:
    """
    Serialize to pickle format.
    
    WARNING: UNSAFE - only use with --unsafe flag and trusted sources!
    """
    if path:
        path = path.with_suffix('.pkl')
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = Path('checkpoint.pkl')
    
    with open(path, 'wb') as f:
        pickle.dump(data, f)
    
    size_bytes = path.stat().st_size
    
    # Calculate checksum before writing
    pickled = pickle.dumps(data)
    checksum = hashlib.sha256(pickled).hexdigest()[:16]
    
    return SerializationResult(
        success=True,
        path=path,
        format=SerializationFormat.PICKLE_UNSAFE,
        size_bytes=size_bytes,
        checksum=checksum,
        compression_ratio=1.0
    )


def deserialize_checkpoint(data: bytes = None, path: Path = None,
                          format: SerializationFormat = None,
                          unsafe_mode: bool = False) -> Tuple[Dict, SerializationResult]:
    """
    Deserialize checkpoint data from file or bytes.
    
    Args:
        data: Serialized data bytes (mutually exclusive with path)
        path: Path to checkpoint file (mutually exclusive with data)
        format: Serialization format (auto-detected if not provided)
        unsafe_mode: Set True to allow PICKLE_UNSAFE format
        
    Returns:
        Tuple of (deserialized_data, SerializationResult)
        
    Raises:
        ValueError: If PICKLE_UNSAFE detected without unsafe_mode
        FileNotFoundError: If path doesn't exist
    """
    logger = logging.getLogger(__name__)
    
    if data is None and path is None:
        return {}, SerializationResult(
            success=False,
            error="Either data or path must be provided"
        )
    
    # Load from path if provided
    if path and data is None:
        if not path.exists():
            return {}, SerializationResult(
                success=False,
                path=path,
                error=f"Checkpoint file not found: {path}"
            )
        
        # Auto-detect format from extension
        if format is None:
            format = _detect_format(path)
        
        with open(path, 'rb') as f:
            data = f.read()
    
    try:
        if format == SerializationFormat.JSON_ZSTD or (path and path.suffix == '.zst'):
            result_data = _deserialize_json_zstd(data)
        elif format == SerializationFormat.JSON or (path and path.suffix in ['.json', '.gz']):
            if path and path.suffix == '.gz':
                result_data = _deserialize_gzip(path)
            else:
                result_data = json.loads(data if isinstance(data, str) else data.decode('utf-8'))
        elif format == SerializationFormat.PICKLE_UNSAFE or (path and path.suffix == '.pkl'):
            if not unsafe_mode:
                error_msg = (
                    "[gap: unsafe_serialization_requires_explicit_flag] "
                    "Pickle checkpoint requires --unsafe flag. "
                    "Refusing to load potentially malicious pickle data."
                )
                logger.error(error_msg)
                return {}, SerializationResult(
                    success=False,
                    format=format or SerializationFormat.PICKLE_UNSAFE,
                    path=path,
                    error=error_msg
                )
            result_data = pickle.loads(data)
        else:
            # Try JSON first (most common)
            try:
                result_data = json.loads(data if isinstance(data, str) else data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}, SerializationResult(
                    success=False,
                    error=f"Unable to detect format for: {path}"
                )
        
        return result_data, SerializationResult(
            success=True,
            path=path,
            format=format,
            size_bytes=len(data) if data else 0
        )
        
    except Exception as e:
        logger.error(f"Deserialization failed: {e}")
        return {}, SerializationResult(
            success=False,
            path=path,
            format=format,
            error=str(e)
        )


def _detect_format(path: Path) -> SerializationFormat:
    """Detect serialization format from file extension."""
    suffix = path.suffix.lower()
    
    if suffix == '.zst':
        return SerializationFormat.JSON_ZSTD
    elif suffix == '.pkl':
        return SerializationFormat.PICKLE_UNSAFE
    elif suffix == '.gz':
        return SerializationFormat.JSON  # gzipped JSON
    else:
        return SerializationFormat.JSON


def _deserialize_json_zstd(data: bytes) -> Dict:
    """Deserialize Zstd-compressed JSON."""
    if not ZSTD_AVAILABLE:
        raise ImportError("zstandard package required for .zst files. Install with: pip install zstandard")
    
    dctx = zstd.ZstdDecompressor()
    decompressed = dctx.decompress(data)
    return json.loads(decompressed.decode('utf-8'))


def _deserialize_gzip(path: Path) -> Dict:
    """Deserialize gzipped JSON."""
    with gzip.open(path, 'rt') as f:
        return json.load(f)


# Legacy compatibility functions
def save_checkpoint_json(path: Path, data: Dict) -> Dict:
    """Legacy: Save checkpoint as JSON (safe, recommended)."""
    result = serialize_checkpoint(data, path, SerializationFormat.JSON)
    return {"format": "json", "safe": True, "path": str(result.path)}


def save_checkpoint_gzip(path: Path, data: Dict) -> Dict:
    """Legacy: Save checkpoint as gzipped JSON."""
    result = _serialize_gzip(data, path)
    return {"format": "gzip", "safe": True, "path": str(result.path)}


def save_checkpoint_zstd(path: Path, data: Dict) -> Dict:
    """Legacy: Save checkpoint with zstd compression (best)."""
    result = serialize_checkpoint(data, path, SerializationFormat.JSON_ZSTD)
    return {
        "format": "zstd",
        "safe": True,
        "path": str(result.path),
        "compression_ratio": result.compression_ratio
    }


def save_checkpoint_pickle(path: Path, data: Dict) -> Dict:
    """
    Legacy: Save checkpoint as pickle.
    
    WARNING: UNSAFE - do not load from untrusted sources!
    Only use with --unsafe flag.
    """
    result = serialize_checkpoint(data, path, SerializationFormat.PICKLE_UNSAFE, unsafe_mode=True)
    return {
        "format": "pickle",
        "safe": False,
        "path": str(result.path),
        "warning": "Do not load from untrusted sources"
    }


def load_checkpoint(path: Path, allow_unsafe: bool = False) -> Dict:
    """
    Legacy: Load checkpoint with format detection.
    
    Args:
        path: Path to checkpoint file
        allow_unsafe: Set True to allow pickle loading (security risk)
        
    Returns:
        Deserialized checkpoint data
        
    Raises:
        ValueError: If pickle detected without allow_unsafe
    """
    data, result = deserialize_checkpoint(path=path, unsafe_mode=allow_unsafe)
    
    if not result.success:
        raise ValueError(result.error)
    
    return data


# =============================================================================
# ITEM-STOR-01: StorageBackend Integration
# =============================================================================

def serialize_checkpoint_to_storage(
    data: Dict,
    backend,  # StorageBackend instance
    path: str,
    format: SerializationFormat = SerializationFormat.JSON_ZSTD,
    unsafe_mode: bool = False,
    metadata: Dict[str, str] = None
) -> SerializationResult:
    """
    Serialize checkpoint data to a StorageBackend.
    
    This function serializes checkpoint data and stores it using the
    provided StorageBackend, enabling cloud storage (S3, GCS) support.
    
    Args:
        data: Checkpoint data dictionary
        backend: StorageBackend instance (Local, S3, or GCS)
        path: Relative path within storage backend
        format: Serialization format (default: JSON_ZSTD)
        unsafe_mode: Set True to allow PICKLE_UNSAFE format
        metadata: Optional metadata to store with checkpoint
        
    Returns:
        SerializationResult with success status and metadata
        
    Example:
        from src.storage import get_storage_backend
        
        backend = get_storage_backend(config)
        result = serialize_checkpoint_to_storage(
            checkpoint_data, 
            backend, 
            "checkpoints/session-123/checkpoint.json"
        )
    """
    logger = logging.getLogger(__name__)
    
    # Safety gate for pickle format
    if format == SerializationFormat.PICKLE_UNSAFE and not unsafe_mode:
        error_msg = (
            "[gap: unsafe_serialization_requires_explicit_flag] "
            "PICKLE_UNSAFE format requires --unsafe CLI flag."
        )
        logger.error(error_msg)
        return SerializationResult(
            success=False,
            format=format,
            error=error_msg
        )
    
    # Add serialization metadata
    data['_serialization'] = {
        'format': format.value,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'safe': format.is_safe,
        'storage_backend': backend.__class__.__name__
    }
    
    try:
        if format == SerializationFormat.JSON_ZSTD:
            serialized_data = _serialize_to_bytes_json_zstd(data)
        elif format == SerializationFormat.JSON:
            serialized_data = _serialize_to_bytes_json(data)
        elif format == SerializationFormat.PICKLE_UNSAFE:
            serialized_data = _serialize_to_bytes_pickle(data)
        else:
            return SerializationResult(
                success=False,
                format=format,
                error=f"Unsupported format: {format}"
            )
        
        # Prepare storage metadata
        storage_metadata = metadata or {}
        storage_metadata['format'] = format.value
        storage_metadata['checksum'] = hashlib.sha256(serialized_data).hexdigest()[:16]
        
        # Save using storage backend
        saved_path = backend.save(path, serialized_data, storage_metadata)
        
        return SerializationResult(
            success=True,
            path=Path(saved_path) if saved_path else None,
            format=format,
            size_bytes=len(serialized_data),
            checksum=storage_metadata['checksum'],
            compression_ratio=1.0  # Calculated separately if needed
        )
        
    except Exception as e:
        logger.error(f"Storage serialization failed: {e}")
        return SerializationResult(
            success=False,
            format=format,
            error=str(e)
        )


def deserialize_checkpoint_from_storage(
    backend,  # StorageBackend instance
    path: str,
    format: SerializationFormat = None,
    unsafe_mode: bool = False
) -> Tuple[Dict, SerializationResult]:
    """
    Deserialize checkpoint data from a StorageBackend.
    
    This function loads and deserializes checkpoint data from the
    provided StorageBackend, enabling cloud storage (S3, GCS) support.
    
    Args:
        backend: StorageBackend instance (Local, S3, or GCS)
        path: Relative path within storage backend
        format: Serialization format (auto-detected if not provided)
        unsafe_mode: Set True to allow PICKLE_UNSAFE format
        
    Returns:
        Tuple of (deserialized_data, SerializationResult)
        
    Example:
        from src.storage import get_storage_backend
        
        backend = get_storage_backend(config)
        data, result = deserialize_checkpoint_from_storage(
            backend,
            "checkpoints/session-123/checkpoint.json"
        )
        if result.success:
            print(f"Loaded checkpoint: {data}")
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Check if path exists
        if not backend.exists(path):
            return {}, SerializationResult(
                success=False,
                path=Path(path),
                error=f"Checkpoint not found in storage: {path}"
            )
        
        # Load from storage backend
        data = backend.load(path)
        
        # Auto-detect format from path if not provided
        if format is None:
            format = _detect_format_from_path(path)
        
        # Deserialize based on format
        if format == SerializationFormat.JSON_ZSTD:
            result_data = _deserialize_json_zstd(data)
        elif format == SerializationFormat.JSON:
            result_data = json.loads(data.decode('utf-8'))
        elif format == SerializationFormat.PICKLE_UNSAFE:
            if not unsafe_mode:
                error_msg = (
                    "[gap: unsafe_serialization_requires_explicit_flag] "
                    "Pickle checkpoint requires --unsafe flag."
                )
                logger.error(error_msg)
                return {}, SerializationResult(
                    success=False,
                    format=format,
                    path=Path(path),
                    error=error_msg
                )
            result_data = pickle.loads(data)
        else:
            # Try JSON first
            try:
                result_data = json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}, SerializationResult(
                    success=False,
                    error=f"Unable to deserialize: {path}"
                )
        
        return result_data, SerializationResult(
            success=True,
            path=Path(path),
            format=format,
            size_bytes=len(data)
        )
        
    except Exception as e:
        logger.error(f"Storage deserialization failed: {e}")
        return {}, SerializationResult(
            success=False,
            path=Path(path),
            error=str(e)
        )


def _serialize_to_bytes_json_zstd(data: Dict) -> bytes:
    """Serialize to JSON + Zstd bytes."""
    if not ZSTD_AVAILABLE:
        # Fallback to plain JSON
        return _serialize_to_bytes_json(data)
    
    json_bytes = json.dumps(data, default=str, indent=2).encode('utf-8')
    cctx = zstd.ZstdCompressor(level=3)
    return cctx.compress(json_bytes)


def _serialize_to_bytes_json(data: Dict) -> bytes:
    """Serialize to plain JSON bytes."""
    return json.dumps(data, default=str, indent=2).encode('utf-8')


def _serialize_to_bytes_pickle(data: Dict) -> bytes:
    """Serialize to pickle bytes (UNSAFE)."""
    return pickle.dumps(data)


def _detect_format_from_path(path: str) -> SerializationFormat:
    """Detect serialization format from path string."""
    path_lower = path.lower()
    
    if path_lower.endswith('.zst') or path_lower.endswith('.json.zst'):
        return SerializationFormat.JSON_ZSTD
    elif path_lower.endswith('.pkl'):
        return SerializationFormat.PICKLE_UNSAFE
    elif path_lower.endswith('.gz'):
        return SerializationFormat.JSON
    else:
        return SerializationFormat.JSON


def get_checkpoint_storage_path(session_id: str, filename: str = "checkpoint.json") -> str:
    """
    Get standard checkpoint path for a session.
    
    Args:
        session_id: Session identifier
        filename: Checkpoint filename
        
    Returns:
        Path like: checkpoints/{session_id}/{filename}
    """
    return f"checkpoints/{session_id}/{filename}"
