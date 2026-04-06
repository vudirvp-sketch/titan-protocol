"""
Safe checkpoint serialization module.

Default: JSON + zstd compression (safe)
Fast mode: pickle with --unsafe flag (not recommended)
"""

import json
import gzip
import pickle
from pathlib import Path
from typing import Dict, Any

try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False


def save_checkpoint_json(path: Path, data: Dict) -> Dict:
    """Save checkpoint as JSON (safe, recommended)."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    return {"format": "json", "safe": True}


def save_checkpoint_gzip(path: Path, data: Dict) -> Dict:
    """Save checkpoint as gzipped JSON."""
    with gzip.open(path.with_suffix('.json.gz'), 'wt') as f:
        json.dump(data, f, indent=2, default=str)
    return {"format": "gzip", "safe": True}


def save_checkpoint_zstd(path: Path, data: Dict) -> Dict:
    """Save checkpoint with zstd compression (best)."""
    if not ZSTD_AVAILABLE:
        return save_checkpoint_gzip(path, data)
    
    cctx = zstd.ZstdCompressor()
    json_bytes = json.dumps(data, default=str).encode('utf-8')
    compressed = cctx.compress(json_bytes)
    
    with open(path.with_suffix('.json.zst'), 'wb') as f:
        f.write(compressed)
    
    return {"format": "zstd", "safe": True, "compression_ratio": len(compressed) / len(json_bytes)}


def save_checkpoint_pickle(path: Path, data: Dict) -> Dict:
    """
    Save checkpoint as pickle.
    
    WARNING: UNSAFE - do not load from untrusted sources!
    Only use with --unsafe flag.
    """
    with open(path.with_suffix('.pkl'), 'wb') as f:
        pickle.dump(data, f)
    return {"format": "pickle", "safe": False, "warning": "Do not load from untrusted sources"}


def load_checkpoint(path: Path, allow_unsafe: bool = False) -> Dict:
    """Load checkpoint with format detection."""
    suffix = path.suffix
    
    if suffix == '.pkl':
        if not allow_unsafe:
            raise ValueError(
                "[gap: unsafe_checkpoint] Pickle checkpoints require --unsafe flag. "
                "Use JSON checkpoints for safety."
            )
        with open(path, 'rb') as f:
            return pickle.load(f)
    
    elif suffix == '.gz':
        with gzip.open(path, 'rt') as f:
            return json.load(f)
    
    elif suffix == '.zst':
        if not ZSTD_AVAILABLE:
            raise ImportError("zstandard package required for .zst files")
        dctx = zstd.ZstdDecompressor()
        with open(path, 'rb') as f:
            decompressed = dctx.decompress(f.read())
        return json.loads(decompressed)
    
    else:  # .json
        with open(path, 'r') as f:
            return json.load(f)
