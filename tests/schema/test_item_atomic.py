"""Tests for Atomic Item schema and Pydantic models (ITEM-B002)."""

import pytest
from pydantic import ValidationError
from src.schema.item_atomic_model import (
    AtomicItem, ItemStatus, SeverityLevel, ValidationCase
)


class TestAtomicItemValid:
    def test_minimal_valid_item(self):
        item = AtomicItem(
            item_id="ITEM_001",
            title="Test Item",
            description="A test description for validation",
            phase="PHASE_2",
            effort="30min",
        )
        assert item.item_id == "ITEM_001"
        assert item.status == ItemStatus.PENDING

    def test_full_valid_item(self):
        item = AtomicItem(
            item_id="ITEM_042",
            title="Complete Item",
            description="A fully populated atomic item for testing",
            phase="PHASE_3",
            status=ItemStatus.IN_PROGRESS,
            effort="2h",
            depends_on=["ITEM_001"],
            gap_tags=["GAP-STRUCT-001"],
            validation_cases=[
                ValidationCase(
                    case_id="VC-TEST-001",
                    condition="item is valid",
                    severity=SeverityLevel.BLOCK,
                )
            ],
            rollback_steps=["rm -f output.txt"],
            artifacts=["output.txt"],
        )
        assert item.status == ItemStatus.IN_PROGRESS


class TestAtomicItemInvalid:
    def test_invalid_item_id_format(self):
        with pytest.raises(ValidationError):
            AtomicItem(
                item_id="INVALID",
                title="Test",
                description="Description text here",
                phase="PHASE_2",
                effort="30min",
            )

    def test_title_too_short(self):
        with pytest.raises(ValidationError):
            AtomicItem(
                item_id="ITEM_001",
                title="AB",
                description="Description text here",
                phase="PHASE_2",
                effort="30min",
            )

    def test_invalid_effort_format(self):
        with pytest.raises(ValidationError):
            AtomicItem(
                item_id="ITEM_001",
                title="Valid Title",
                description="Description text here",
                phase="PHASE_2",
                effort="about an hour",
            )

    def test_invalid_depends_on_format(self):
        with pytest.raises(ValidationError):
            AtomicItem(
                item_id="ITEM_001",
                title="Valid Title",
                description="Description text here",
                phase="PHASE_2",
                effort="30min",
                depends_on=["INVALID"],
            )

    def test_description_too_short(self):
        with pytest.raises(ValidationError):
            AtomicItem(
                item_id="ITEM_001",
                title="Valid Title",
                description="short",
                phase="PHASE_2",
                effort="30min",
            )

    def test_invalid_phase_format(self):
        with pytest.raises(ValidationError):
            AtomicItem(
                item_id="ITEM_001",
                title="Valid Title",
                description="Description text here",
                phase="INVALID",
                effort="30min",
            )


class TestValidationCase:
    def test_valid_validation_case(self):
        vc = ValidationCase(
            case_id="VC-TEST-001",
            condition="test condition passes",
            severity=SeverityLevel.BLOCK,
        )
        assert vc.severity == SeverityLevel.BLOCK

    def test_validation_case_with_gap_tag(self):
        vc = ValidationCase(
            case_id="VC-VAL-001",
            condition="validation gap detected",
            severity=SeverityLevel.GAP_TAG,
            gap_tag="GAP-VAL-001",
        )
        assert vc.gap_tag == "GAP-VAL-001"

    def test_invalid_case_id_format(self):
        with pytest.raises(ValidationError):
            ValidationCase(
                case_id="INVALID",
                condition="test condition",
                severity=SeverityLevel.WARN,
            )
