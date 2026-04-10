"""GapEvent Serializer for TITAN Protocol.

ITEM-B004: Complete GapEvent serialization using ALL 20 mappings from
adapter_mapping.yaml. Supports from_legacy_gap(), to_legacy_gap(),
and validate_round_trip() for bidirectional conversion.
"""

from __future__ import annotations
import yaml
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any


@dataclass
class GapEvent:
    gap_id: str
    gap_type: str
    category: str
    severity: str
    description: str
    source_component: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    related_patterns: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    legacy_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), default_flow_style=False, allow_unicode=True)


_MAPPING_CACHE: Optional[Dict[str, dict]] = None
_REVERSE_CACHE: Optional[Dict[str, dict]] = None


def _load_mappings() -> Dict[str, dict]:
    global _MAPPING_CACHE
    if _MAPPING_CACHE is not None:
        return _MAPPING_CACHE
    mapping_path = Path(__file__).parent / "adapter_mapping.yaml"
    if not mapping_path.exists():
        raise FileNotFoundError(
            f"adapter_mapping.yaml not found at {mapping_path}. "
            "Complete Plan A first."
        )
    data = yaml.safe_load(mapping_path.read_text())
    _MAPPING_CACHE = {}
    for entry in data.get("mappings", []):
        _MAPPING_CACHE[entry["gap_type"]] = entry
    return _MAPPING_CACHE


def _load_reverse_mappings() -> Dict[str, dict]:
    global _REVERSE_CACHE
    if _REVERSE_CACHE is not None:
        return _REVERSE_CACHE
    mappings = _load_mappings()
    _REVERSE_CACHE = {}
    for gap_type, entry in mappings.items():
        for legacy_key in entry.get("legacy_keys", []):
            _REVERSE_CACHE[legacy_key] = entry
    return _REVERSE_CACHE


def _clear_cache() -> None:
    """Clear mapping caches (useful for testing)."""
    global _MAPPING_CACHE, _REVERSE_CACHE
    _MAPPING_CACHE = None
    _REVERSE_CACHE = None


def from_legacy_gap(legacy_data: dict) -> GapEvent:
    """Convert a legacy gap dict to canonical GapEvent using ALL 20 mappings."""
    reverse_map = _load_reverse_mappings()
    legacy_type = legacy_data.get("type", legacy_data.get("gap_type", ""))
    mapping_entry = reverse_map.get(legacy_type)
    if mapping_entry is None:
        forward_map = _load_mappings()
        mapping_entry = forward_map.get(legacy_type)
    if mapping_entry is None:
        return GapEvent(
            gap_id=f"GAP-UNMAPPED-{legacy_type}",
            gap_type="GAP-ADAPT-001",
            category="ADAPT",
            severity="WARN",
            description=f"Unmapped legacy gap type: {legacy_type}",
            source_component="serializer",
            legacy_id=legacy_type,
            context={"original_data": legacy_data},
        )
    return GapEvent(
        gap_id=mapping_entry.get("gap_type", "GAP-UNKNOWN"),
        gap_type=mapping_entry.get("gap_type", ""),
        category=mapping_entry.get("category", "INTEG"),
        severity=mapping_entry.get("severity", "WARN"),
        description=legacy_data.get("message", mapping_entry.get("description", "")),
        source_component=legacy_data.get("source", "unknown"),
        related_patterns=mapping_entry.get("related_patterns", []),
        legacy_id=legacy_type,
        context={"mapping_used": mapping_entry.get("gap_type"), "original_data": legacy_data},
    )


def to_legacy_gap(event: GapEvent) -> dict:
    """Convert canonical GapEvent back to legacy format."""
    forward_map = _load_mappings()
    mapping_entry = forward_map.get(event.gap_type, {})
    legacy_keys = mapping_entry.get("legacy_keys", [event.gap_type])
    primary_legacy_key = legacy_keys[0] if legacy_keys else event.gap_type
    result = {
        "type": primary_legacy_key,
        "gap_type": event.gap_type,
        "message": event.description,
        "source": event.source_component,
        "severity": event.severity,
        "category": event.category,
        "timestamp": event.timestamp,
    }
    if event.context and "original_data" in event.context:
        for k, v in event.context["original_data"].items():
            if k not in result:
                result[k] = v
    return result


def validate_round_trip(legacy_data: dict) -> bool:
    """Validate legacy->canonical->legacy round-trip preserves semantics."""
    canonical = from_legacy_gap(legacy_data)
    roundtrip = to_legacy_gap(canonical)
    checks = {
        "severity_preserved": roundtrip.get("severity") == legacy_data.get("severity", canonical.severity),
        "description_preserved": roundtrip.get("message") == legacy_data.get("message", canonical.description),
        "source_preserved": roundtrip.get("source") == legacy_data.get("source", canonical.source_component),
        "type_mappable": canonical.gap_type != "GAP-ADAPT-001" or not legacy_data.get("type", ""),
    }
    return all(checks.values())
