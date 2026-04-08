"""
Tests for Cross-Reference Validator (ITEM-INT-102).
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from src.validation.crossref_validator import (
    CrossRefValidator,
    ReferenceType,
    ReferenceStatus,
    Reference,
    BrokenRef,
    ValidationResult,
    create_crossref_validator
)


class TestReferenceType:
    """Tests for ReferenceType enum."""
    
    def test_reference_types(self):
        """Test that all reference types exist."""
        assert ReferenceType.SECTION.value == "section"
        assert ReferenceType.ANCHOR.value == "anchor"
        assert ReferenceType.FILE.value == "file"
        assert ReferenceType.CODE_IMPORT.value == "code_import"
        assert ReferenceType.IMAGE.value == "image"
        assert ReferenceType.LINK.value == "link"


class TestReferenceStatus:
    """Tests for ReferenceStatus enum."""
    
    def test_status_values(self):
        """Test that all status values exist."""
        assert ReferenceStatus.VALID.value == "valid"
        assert ReferenceStatus.BROKEN.value == "broken"
        assert ReferenceStatus.AMBIGUOUS.value == "ambiguous"
        assert ReferenceStatus.EXTERNAL.value == "external"


class TestReference:
    """Tests for Reference dataclass."""
    
    def test_reference_creation(self):
        """Test creating a reference."""
        ref = Reference(
            ref_type=ReferenceType.ANCHOR,
            source_file="test.md",
            source_line=10,
            target="#section",
            anchor="section"
        )
        
        assert ref.ref_type == ReferenceType.ANCHOR
        assert ref.source_file == "test.md"
        assert ref.source_line == 10
        assert ref.target == "#section"
        assert ref.anchor == "section"
    
    def test_reference_to_dict(self):
        """Test converting reference to dictionary."""
        ref = Reference(
            ref_type=ReferenceType.FILE,
            source_file="doc.md",
            source_line=5,
            target="other.md",
            target_file="other.md",
            anchor="intro",
            status=ReferenceStatus.BROKEN,
            message="File not found"
        )
        
        data = ref.to_dict()
        
        assert data["ref_type"] == "file"
        assert data["source_file"] == "doc.md"
        assert data["target_file"] == "other.md"
        assert data["status"] == "broken"


class TestBrokenRef:
    """Tests for BrokenRef dataclass."""
    
    def test_broken_ref_creation(self):
        """Test creating a broken reference."""
        ref = Reference(
            ref_type=ReferenceType.FILE,
            source_file="test.md",
            source_line=1,
            target="missing.md"
        )
        
        broken = BrokenRef(
            reference=ref,
            suggestions=["existing.md", "other.md"],
            severity="high"
        )
        
        assert broken.reference == ref
        assert len(broken.suggestions) == 2
        assert broken.severity == "high"
    
    def test_broken_ref_to_dict(self):
        """Test converting broken ref to dictionary."""
        ref = Reference(
            ref_type=ReferenceType.ANCHOR,
            source_file="test.md",
            source_line=1,
            target="#missing"
        )
        
        broken = BrokenRef(reference=ref, suggestions=[], severity="medium")
        data = broken.to_dict()
        
        assert "reference" in data
        assert data["severity"] == "medium"


class TestCrossRefValidator:
    """Tests for CrossRefValidator class."""
    
    def test_initialization(self):
        """Test validator initialization."""
        validator = CrossRefValidator()
        
        assert validator._broken_threshold == 0.05
        assert validator._check_images is True
        assert validator._check_code_imports is True
    
    def test_initialization_with_config(self):
        """Test validator initialization with config."""
        config = {
            "validation": {
                "crossref_broken_threshold": 0.1,
                "validate_image_refs": False
            }
        }
        
        validator = CrossRefValidator(config)
        
        assert validator._broken_threshold == 0.1
        assert validator._check_images is False
    
    def test_validate_references_empty(self):
        """Test validation with no files."""
        validator = CrossRefValidator()
        result = validator.validate_references([])
        
        assert result.total_refs == 0
        assert result.broken_refs == 0
        assert result.passed is True
    
    def test_validate_references_single_file(self):
        """Test validation with a single valid file."""
        validator = CrossRefValidator()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("# Test Document\n\nContent here.\n")
            
            result = validator.validate_references([str(test_file)])
            
            # Should have 0 broken refs for a file with no references
            assert isinstance(result, ValidationResult)
            assert result.total_refs >= 0
    
    def test_validate_anchor_reference(self):
        """Test validation of anchor references."""
        validator = CrossRefValidator()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file with anchor
            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("# Section One\n\nContent.\n\n[Link](#section-one)\n")
            
            result = validator.validate_references([str(test_file)])
            
            # Should find the anchor reference
            assert result.total_refs >= 1
    
    def test_get_stats(self):
        """Test getting validator statistics."""
        validator = CrossRefValidator()
        stats = validator.get_stats()
        
        assert "broken_threshold" in stats
        assert "check_images" in stats
        assert "check_code_imports" in stats
    
    def test_clear_cache(self):
        """Test clearing the cache."""
        validator = CrossRefValidator()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("# Test\n")
            
            validator.validate_references([str(test_file)])
            
            assert len(validator._file_index) > 0
            
            validator.clear_cache()
            
            assert len(validator._file_index) == 0
    
    def test_set_event_bus(self):
        """Test setting event bus."""
        validator = CrossRefValidator()
        mock_bus = Mock()
        
        validator.set_event_bus(mock_bus)
        
        assert validator._event_bus == mock_bus


class TestValidationResult:
    """Tests for ValidationResult dataclass."""
    
    def test_result_creation(self):
        """Test creating a validation result."""
        result = ValidationResult(
            total_refs=10,
            valid_refs=8,
            broken_refs=2,
            broken_rate=0.2,
            passed=False,
            message="2 broken references found"
        )
        
        assert result.total_refs == 10
        assert result.valid_refs == 8
        assert result.broken_refs == 2
        assert result.broken_rate == 0.2
        assert result.passed is False
    
    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = ValidationResult(
            total_refs=5,
            valid_refs=5,
            broken_refs=0,
            passed=True,
            message="All references valid"
        )
        
        data = result.to_dict()
        
        assert data["total_refs"] == 5
        assert data["passed"] is True


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_crossref_validator_default(self):
        """Test creating validator with defaults."""
        validator = create_crossref_validator()
        
        assert isinstance(validator, CrossRefValidator)
    
    def test_create_crossref_validator_with_config(self):
        """Test creating validator with config."""
        config = {"validation": {"crossref_broken_threshold": 0.15}}
        validator = create_crossref_validator(config)
        
        assert validator._broken_threshold == 0.15
    
    def test_create_crossref_validator_with_event_bus(self):
        """Test creating validator with event bus."""
        mock_bus = Mock()
        validator = create_crossref_validator(event_bus=mock_bus)
        
        assert validator._event_bus == mock_bus
