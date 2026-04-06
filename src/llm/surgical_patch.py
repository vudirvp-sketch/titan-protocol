#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Surgical Patch Engine (GUARDIAN)

Implements the Surgical Patch Engine from PROTOCOL.md Phase 4:
- Pre-patch idempotency check (INVAR-04)
- Targeted replacements only
- Max 2 patch iterations per defect
- Validation protocol

This engine ensures minimal, surgical changes to documents without
regenerating full content.

Usage:
    from src.llm import SurgicalPatchEngine
    
    engine = SurgicalPatchEngine(source_file, working_copy)
    
    # Apply a patch
    result = engine.apply_patch(
        location="L45-52",
        old_pattern="old text",
        new_pattern="new text",
        reason="Fix typo"
    )
    
    if result.success:
        print(f"Patch applied: {result}")
    else:
        print(f"Patch failed: {result.error}")
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class PatchStatus(Enum):
    """Status of a patch operation."""
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    ALREADY_APPLIED = "ALREADY_APPLIED"


@dataclass
class PatchResult:
    """Result of a patch operation."""
    success: bool
    status: PatchStatus
    location: str
    old_pattern: str
    new_pattern: str
    reason: str
    chunk_id: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    error: Optional[str] = None
    iteration: int = 1
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "status": self.status.value,
            "location": self.location,
            "old_pattern": self.old_pattern[:100] + "..." if len(self.old_pattern) > 100 else self.old_pattern,
            "new_pattern": self.new_pattern[:100] + "..." if len(self.new_pattern) > 100 else self.new_pattern,
            "reason": self.reason,
            "chunk_id": self.chunk_id,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "error": self.error,
            "iteration": self.iteration,
            "timestamp": self.timestamp
        }


@dataclass
class ValidationCheck:
    """Result of a validation check."""
    name: str
    passed: bool
    message: str
    details: Optional[Dict] = None


class SurgicalPatchEngine:
    """
    Surgical Patch Engine (GUARDIAN) for targeted document modifications.
    
    Implements:
    - PRE-PATCH IDEMPOTENCY CHECK (INVAR-04)
    - VALIDATION_PROTOCOL with targeted fixes
    - Max 2 patch iterations per defect
    
    Rules:
    ├─ NEVER regenerate full document
    ├─ Targeted replacements only
    ├─ Max 2 patch iterations per defect
    ├─ Patch format: `Replace: [Target] -> With: [New]`
    └─ Failed patches → mark `[gap: ...]` + proceed
    
    Example:
        engine = SurgicalPatchEngine(
            source_file="original.md",
            working_copy="working.md"
        )
        
        # Apply a surgical patch
        result = engine.apply_patch(
            location="L45-52",
            old_pattern="defective text",
            new_pattern="corrected text",
            reason="Fix typo in section 3"
        )
    """
    
    MAX_PATCH_ITERATIONS = 2
    
    def __init__(self, 
                 source_file: Optional[str] = None,
                 working_copy: Optional[str] = None,
                 content: Optional[str] = None):
        """
        Initialize the Surgical Patch Engine.
        
        Args:
            source_file: Path to the original source file (read-only)
            working_copy: Path to the working copy (modifiable)
            content: In-memory content if no file paths
        """
        self.source_file = Path(source_file) if source_file else None
        self.working_copy = Path(working_copy) if working_copy else None
        
        # Load content
        if content is not None:
            self.content = content
            self.content_lines = content.split('\n')
        elif self.working_copy and self.working_copy.exists():
            with open(self.working_copy) as f:
                self.content = f.read()
                self.content_lines = self.content.split('\n')
        elif self.source_file and self.source_file.exists():
            with open(self.source_file) as f:
                self.content = f.read()
                self.content_lines = self.content.split('\n')
        else:
            self.content = ""
            self.content_lines = []
        
        # Source content for comparison (never modified)
        self.source_content = self._load_source_content()
        
        # Patch history
        self.patch_history: List[PatchResult] = []
        self.validation_checks: List[ValidationCheck] = []
        
        # Track line offsets from previous patches
        self.line_offsets: Dict[str, int] = {}  # chunk_id -> offset
    
    def _load_source_content(self) -> str:
        """Load original source content for comparison."""
        if self.source_file and self.source_file.exists():
            with open(self.source_file) as f:
                return f.read()
        return self.content
    
    def apply_patch(self,
                    location: str,
                    old_pattern: str,
                    new_pattern: str,
                    reason: str,
                    chunk_id: Optional[str] = None,
                    iteration: int = 1) -> PatchResult:
        """
        Apply a surgical patch to the content.
        
        PRE-PATCH IDEMPOTENCY CHECK (INVAR-04):
          BEFORE applying any patch:
            IF target_section already matches desired state:
              └─ SKIP patch → log [SKIPPED — already applied] → continue
        
        Args:
            location: Location specification (e.g., "L45-52" or "C3:118")
            old_pattern: Text to replace
            new_pattern: Replacement text
            reason: Rationale for the change
            chunk_id: Optional chunk identifier
            iteration: Current iteration (1 or 2)
            
        Returns:
            PatchResult with status and details
        """
        # Parse location
        line_start, line_end = self._parse_location(location)
        
        # IDEMPOTENCY CHECK: Check if already applied
        if self._check_idempotency(new_pattern, line_start, line_end):
            result = PatchResult(
                success=True,
                status=PatchStatus.ALREADY_APPLIED,
                location=location,
                old_pattern=old_pattern,
                new_pattern=new_pattern,
                reason=reason,
                chunk_id=chunk_id,
                line_start=line_start,
                line_end=line_end,
                iteration=iteration
            )
            self.patch_history.append(result)
            return result
        
        # Find the old pattern in the specified location
        found, actual_lines = self._find_pattern(old_pattern, line_start, line_end)
        
        if not found:
            # Pattern not found - might have already been changed
            result = PatchResult(
                success=False,
                status=PatchStatus.FAILED,
                location=location,
                old_pattern=old_pattern,
                new_pattern=new_pattern,
                reason=reason,
                chunk_id=chunk_id,
                line_start=line_start,
                line_end=line_end,
                error="Pattern not found at specified location",
                iteration=iteration
            )
            self.patch_history.append(result)
            return result
        
        # Apply the patch
        try:
            self._apply_replacement(actual_lines, old_pattern, new_pattern)
            
            result = PatchResult(
                success=True,
                status=PatchStatus.APPLIED,
                location=location,
                old_pattern=old_pattern,
                new_pattern=new_pattern,
                reason=reason,
                chunk_id=chunk_id,
                line_start=actual_lines[0],
                line_end=actual_lines[-1],
                iteration=iteration
            )
            
        except Exception as e:
            result = PatchResult(
                success=False,
                status=PatchStatus.FAILED,
                location=location,
                old_pattern=old_pattern,
                new_pattern=new_pattern,
                reason=reason,
                chunk_id=chunk_id,
                line_start=line_start,
                line_end=line_end,
                error=str(e),
                iteration=iteration
            )
        
        self.patch_history.append(result)
        return result
    
    def _parse_location(self, location: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Parse location string to line numbers.
        
        Formats:
        - "L45-52" → (44, 52)  (0-indexed)
        - "L45" → (44, 45)
        - "C3:118" → chunk-based (requires chunk map)
        """
        # Handle "L{start}-{end}" format
        match = re.match(r'L(\d+)(?:-(\d+))?', location)
        if match:
            start = int(match.group(1)) - 1  # Convert to 0-indexed
            end = int(match.group(2)) if match.group(2) else start + 1
            return (start, end)
        
        # Handle chunk-based format (C3:118)
        # Would need chunk map integration
        match = re.match(r'C(\d+):(\d+)', location)
        if match:
            # For now, return None - would integrate with NAV_MAP
            return (None, None)
        
        return (None, None)
    
    def _check_idempotency(self, new_pattern: str, 
                           line_start: Optional[int],
                           line_end: Optional[int]) -> bool:
        """
        Check if patch is already applied (idempotency).
        
        IF target_section already matches desired state → SKIP (no-op)
        """
        if line_start is None:
            return False
        
        if line_start >= len(self.content_lines):
            return False
        
        actual_end = line_end or line_start + 1
        current_section = '\n'.join(
            self.content_lines[line_start:actual_end]
        )
        
        # Normalize for comparison
        current_normalized = current_section.strip()
        new_normalized = new_pattern.strip()
        
        return current_normalized == new_normalized
    
    def _find_pattern(self, pattern: str, 
                      line_start: Optional[int],
                      line_end: Optional[int]) -> Tuple[bool, List[int]]:
        """
        Find the pattern in the content.
        
        Returns (found, line_numbers).
        """
        if not pattern:
            return (False, [])
        
        # If location specified, search within that range
        if line_start is not None:
            search_start = max(0, line_start - 5)  # Allow some flexibility
            search_end = min(len(self.content_lines), (line_end or line_start) + 5)
            search_lines = self.content_lines[search_start:search_end]
            
            # Try exact match
            pattern_lines = pattern.strip().split('\n')
            for i in range(len(search_lines) - len(pattern_lines) + 1):
                if search_lines[i:i+len(pattern_lines)] == pattern_lines:
                    return (True, list(range(search_start + i, search_start + i + len(pattern_lines))))
            
            # Try normalized match
            pattern_normalized = [l.strip() for l in pattern_lines]
            for i in range(len(search_lines) - len(pattern_lines) + 1):
                if [l.strip() for l in search_lines[i:i+len(pattern_lines)]] == pattern_normalized:
                    return (True, list(range(search_start + i, search_start + i + len(pattern_lines))))
        
        # Otherwise search entire content
        pattern_lines = pattern.strip().split('\n')
        for i in range(len(self.content_lines) - len(pattern_lines) + 1):
            if self.content_lines[i:i+len(pattern_lines)] == pattern_lines:
                return (True, list(range(i, i + len(pattern_lines))))
        
        return (False, [])
    
    def _apply_replacement(self, line_numbers: List[int], 
                          old_pattern: str, new_pattern: str) -> None:
        """Apply the replacement to the content."""
        if not line_numbers:
            return
        
        old_lines = old_pattern.split('\n')
        new_lines = new_pattern.split('\n')
        
        # Calculate offset for future patches
        offset_delta = len(new_lines) - len(old_lines)
        
        # Replace the lines
        start = line_numbers[0]
        end = line_numbers[-1] + 1
        
        self.content_lines = (
            self.content_lines[:start] + 
            new_lines + 
            self.content_lines[end:]
        )
        
        # Update content string
        self.content = '\n'.join(self.content_lines)
        
        # Track offset
        if offset_delta != 0:
            for chunk_id, offset in list(self.line_offsets.items()):
                # Update offsets for chunks after this one
                pass  # Would need chunk boundary info
    
    def validate(self, checks: Optional[List[str]] = None) -> List[ValidationCheck]:
        """
        Run validation checks on the modified content.
        
        VALIDATION_CHECKLIST:
          PASS CONDITIONS:
            [ ] grep confirms old pattern removed
            [ ] grep confirms new pattern present
            [ ] Cross-reference check: no broken links/imports
            [ ] Complexity score did not increase
            [ ] No new SEV-1/SEV-2 issues introduced
            [ ] KEEP markers preserved
            [ ] No forbidden patterns introduced
        
        Args:
            checks: Optional list of specific checks to run
            
        Returns:
            List of ValidationCheck results
        """
        self.validation_checks = []
        
        # Default checks
        if checks is None:
            checks = [
                "old_pattern_removed",
                "new_pattern_present",
                "keep_markers_preserved",
                "no_forbidden_patterns"
            ]
        
        for check_name in checks:
            check = self._run_validation_check(check_name)
            self.validation_checks.append(check)
        
        return self.validation_checks
    
    def _run_validation_check(self, check_name: str) -> ValidationCheck:
        """Run a specific validation check."""
        if check_name == "old_pattern_removed":
            return self._check_old_pattern_removed()
        elif check_name == "new_pattern_present":
            return self._check_new_pattern_present()
        elif check_name == "keep_markers_preserved":
            return self._check_keep_markers()
        elif check_name == "no_forbidden_patterns":
            return self._check_forbidden_patterns()
        elif check_name == "no_broken_refs":
            return self._check_broken_refs()
        else:
            return ValidationCheck(
                name=check_name,
                passed=False,
                message=f"Unknown check: {check_name}"
            )
    
    def _check_old_pattern_removed(self) -> ValidationCheck:
        """Check that old patterns were removed."""
        for patch in self.patch_history:
            if patch.status == PatchStatus.APPLIED:
                if patch.old_pattern in self.content:
                    return ValidationCheck(
                        name="old_pattern_removed",
                        passed=False,
                        message=f"Old pattern still present after patch at {patch.location}"
                    )
        
        return ValidationCheck(
            name="old_pattern_removed",
            passed=True,
            message="All old patterns removed"
        )
    
    def _check_new_pattern_present(self) -> ValidationCheck:
        """Check that new patterns are present."""
        for patch in self.patch_history:
            if patch.status == PatchStatus.APPLIED:
                if patch.new_pattern not in self.content:
                    return ValidationCheck(
                        name="new_pattern_present",
                        passed=False,
                        message=f"New pattern not found after patch at {patch.location}"
                    )
        
        return ValidationCheck(
            name="new_pattern_present",
            passed=True,
            message="All new patterns present"
        )
    
    def _check_keep_markers(self) -> ValidationCheck:
        """Check that KEEP markers are preserved."""
        # Find KEEP markers in source
        keep_pattern = re.compile(r'<!--\s*KEEP\s*-->')
        source_keeps = keep_pattern.findall(self.source_content)
        current_keeps = keep_pattern.findall(self.content)
        
        if len(source_keeps) != len(current_keeps):
            return ValidationCheck(
                name="keep_markers_preserved",
                passed=False,
                message=f"KEEP marker count changed: {len(source_keeps)} → {len(current_keeps)}"
            )
        
        return ValidationCheck(
            name="keep_markers_preserved",
            passed=True,
            message=f"All {len(source_keeps)} KEEP markers preserved"
        )
    
    def _check_forbidden_patterns(self) -> ValidationCheck:
        """Check that no forbidden patterns were introduced."""
        forbidden = [
            r'> ⚠',  # Warnings (except GATE markers)
            r'> ✓.*(?<!GATE)',  # Interim checks
            r'\[verify recency\]',  # Temporary markers
            r'~~.*~~',  # Strikethrough (debug artifact)
        ]
        
        for pattern in forbidden:
            matches = re.findall(pattern, self.content)
            if matches:
                return ValidationCheck(
                    name="no_forbidden_patterns",
                    passed=False,
                    message=f"Forbidden pattern found: {pattern}",
                    details={"matches": matches[:5]}
                )
        
        return ValidationCheck(
            name="no_forbidden_patterns",
            passed=True,
            message="No forbidden patterns introduced"
        )
    
    def _check_broken_refs(self) -> ValidationCheck:
        """Check for broken cross-references."""
        # Find all [text](link) patterns
        ref_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        refs = ref_pattern.findall(self.content)
        
        broken = []
        for text, link in refs:
            # Check if it's an internal reference
            if link.startswith('#'):
                # Anchor reference
                anchor = link[1:]
                if f'id="{anchor}"' not in self.content and f'name="{anchor}"' not in self.content:
                    broken.append(link)
            elif link.startswith('http'):
                # External link - skip
                pass
            else:
                # File reference
                if self.working_copy:
                    target = self.working_copy.parent / link
                    if not target.exists():
                        broken.append(link)
        
        if broken:
            return ValidationCheck(
                name="no_broken_refs",
                passed=False,
                message=f"Broken references found: {broken[:5]}",
                details={"broken_refs": broken}
            )
        
        return ValidationCheck(
            name="no_broken_refs",
            passed=True,
            message="No broken references"
        )
    
    def save(self, output_path: Optional[str] = None) -> bool:
        """
        Save the modified content.
        
        Args:
            output_path: Optional output path (defaults to working_copy)
            
        Returns:
            True if save successful
        """
        path = Path(output_path) if output_path else self.working_copy
        if not path:
            return False
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                f.write(self.content)
            return True
        except Exception:
            return False
    
    def get_change_log(self) -> List[Dict]:
        """Get change log for all patches."""
        return [p.to_dict() for p in self.patch_history]
    
    def get_checksum(self) -> str:
        """Get SHA-256 checksum of current content."""
        return hashlib.sha256(self.content.encode()).hexdigest()
    
    def rollback(self) -> bool:
        """
        Rollback to source content.
        
        Returns:
            True if rollback successful
        """
        if self.source_content:
            self.content = self.source_content
            self.content_lines = self.source_content.split('\n')
            self.patch_history = []
            return True
        return False


def create_patch_engine(source_file: str, 
                        working_copy: Optional[str] = None) -> SurgicalPatchEngine:
    """
    Factory function to create SurgicalPatchEngine.
    
    Args:
        source_file: Path to source file
        working_copy: Optional path to working copy
        
    Returns:
        Configured SurgicalPatchEngine instance
    """
    return SurgicalPatchEngine(source_file=source_file, working_copy=working_copy)
