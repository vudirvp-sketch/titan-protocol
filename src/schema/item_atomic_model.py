"""Pydantic models for Atomic Item schema (PAT-01).

ITEM-B002: Canonical Pydantic validation models for the atomic item
work unit in TITAN Protocol.
"""

from __future__ import annotations
import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ItemStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"


class SeverityLevel(str, Enum):
    BLOCK = "BLOCK"
    WARN = "WARN"
    GAP_TAG = "GAP_TAG"


class ValidationCase(BaseModel):
    case_id: str = Field(..., pattern=r"^VC-[A-Z]+-\d{3}$")
    condition: str = Field(..., min_length=5)
    severity: SeverityLevel
    gap_tag: Optional[str] = None


class AtomicItem(BaseModel):
    item_id: str = Field(..., pattern=r"^ITEM_\d{3}$")
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10)
    phase: str = Field(..., pattern=r"^PHASE_\d+$")
    status: ItemStatus = ItemStatus.PENDING
    effort: str = Field(..., pattern=r"^\d+(min|h|days?)$")
    depends_on: List[str] = Field(default_factory=list)
    gap_tags: List[str] = Field(default_factory=list)
    validation_cases: List[ValidationCase] = Field(default_factory=list)
    rollback_steps: List[str] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)

    @field_validator("depends_on")
    @classmethod
    def validate_depends_on_format(cls, v: List[str]) -> List[str]:
        for dep in v:
            if not re.match(r"^ITEM_\d{3}$", dep):
                raise ValueError(f"Invalid depends_on reference: {dep}")
        return v
