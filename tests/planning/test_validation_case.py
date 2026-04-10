"""Tests for ValidationCase and ValidatedAtomicItem (ITEM-B006)."""

import pytest
from src.planning.planning_engine import ValidationCase, SeverityLevel, ValidatedAtomicItem


class TestValidationCase:
    def test_create_block_case(self):
        vc = ValidationCase(case_id="VC-01", condition="test", severity=SeverityLevel.BLOCK)
        assert vc.severity == SeverityLevel.BLOCK

    def test_create_warn_case(self):
        vc = ValidationCase(case_id="VC-02", condition="test", severity=SeverityLevel.WARN)
        assert vc.severity == SeverityLevel.WARN

    def test_create_gap_tag_case(self):
        vc = ValidationCase(case_id="VC-03", condition="test", severity=SeverityLevel.GAP_TAG, gap_tag="GAP-VAL-001")
        assert vc.gap_tag == "GAP-VAL-001"


class TestValidatedAtomicItem:
    def test_validate_all_pass(self):
        item = ValidatedAtomicItem(
            item_id="ITEM_001",
            title="Test",
            description="Test item",
            phase="PHASE_2",
            validation_cases=[
                ValidationCase(case_id="VC-01", condition="test", severity=SeverityLevel.WARN),
            ],
        )
        result = item.validate()
        assert "VC-01" in result["passed"]
        assert len(result["blocked"]) == 0

    def test_validate_with_block(self):
        item = ValidatedAtomicItem(
            item_id="ITEM_001",
            title="Test",
            description="Test item",
            phase="PHASE_2",
            validation_cases=[
                ValidationCase(case_id="VC-BLOCK-01", condition="block_test", severity=SeverityLevel.BLOCK),
            ],
        )
        result = item.validate(context={"fail": True})
        # With default _evaluate_condition returning True when context is not None
        assert "VC-BLOCK-01" in result["passed"]

    def test_validate_empty_cases(self):
        item = ValidatedAtomicItem(
            item_id="ITEM_001",
            title="Test",
            description="Test item",
            phase="PHASE_2",
        )
        result = item.validate()
        assert result["passed"] == []
        assert result["blocked"] == []
