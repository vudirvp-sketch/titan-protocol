"""
TITAN FUSE Protocol - Input Sanitizer

ITEM_016: InputSanitizer for TITAN Protocol v1.2.0

Sanitizes user inputs for security with enhanced detection capabilities.
Implements multiple sanitization actions based on threat severity.

Key Features:
- Prompt injection detection with multiple action modes
- HTML injection escaping
- Control character removal
- Unicode homoglyph detection
- Base64 pattern detection
- ROT13 variant detection
- Case-insensitive pattern matching
- Configurable severity-based actions

Integration Points:
- IntentEnricher: Uses InputSanitizer for request sanitization
- EventBus: Emits SECURITY_ALERT events
- UniversalRouter: First line of defense for all inputs

Author: TITAN FUSE Team
Version: 1.2.0
"""

import re
import base64
import html
import codecs
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List, Set
import logging
import unicodedata

from src.events.event_bus import Event, EventSeverity, EventBus
from src.utils.timezone import now_utc_iso


class SanitizationAction(Enum):
    """
    Actions to take when sanitization issues are detected.
    
    Actions:
    - NONE: No action taken
    - ESCAPE: Escape dangerous content
    - REMOVE: Remove dangerous content
    - REJECT: Reject the entire request
    - DROP: Silently drop dangerous content
    - ISOLATE: Isolate request in sandbox (if available)
    - SANITIZE_AND_WARN: Sanitize and log warning
    """
    NONE = "none"
    ESCAPE = "escape"
    REMOVE = "remove"
    REJECT = "reject"
    DROP = "drop"
    ISOLATE = "isolate"
    SANITIZE_AND_WARN = "sanitize_and_warn"


class ThreatSeverity(Enum):
    """
    Severity levels for detected threats.
    
    Levels:
    - CRITICAL: Must reject request
    - HIGH: Should reject or isolate
    - MEDIUM: Should sanitize or warn
    - LOW: Can escape or warn
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ModificationRecord:
    """
    Record of a modification made during sanitization.
    
    Attributes:
        position: Position in the original text
        original: Original content
        modified: Modified content
        rule_name: Name of the rule that triggered
        action: Action taken
    """
    position: int = 0
    original: str = ""
    modified: str = ""
    rule_name: str = ""
    action: SanitizationAction = SanitizationAction.NONE
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "position": self.position,
            "original": self.original,
            "modified": self.modified,
            "rule_name": self.rule_name,
            "action": self.action.value,
        }


@dataclass
class SanitizationResult:
    """
    Result of sanitization operation.
    
    Attributes:
        original: Original input text
        sanitized: Sanitized output text
        was_modified: Whether any modifications were made
        modifications: List of modifications made
        action_taken: Final action taken
        rejected: Whether the request was rejected
        rejection_reason: Reason for rejection if rejected
    """
    original: str
    sanitized: str
    was_modified: bool = False
    modifications: List[ModificationRecord] = field(default_factory=list)
    action_taken: SanitizationAction = SanitizationAction.NONE
    rejected: bool = False
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "original": self.original,
            "sanitized": self.sanitized,
            "was_modified": self.was_modified,
            "modifications": [m.to_dict() for m in self.modifications],
            "action_taken": self.action_taken.value,
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class InjectionResult:
    """
    Result of injection detection.
    
    Attributes:
        detected: Whether injection was detected
        patterns_matched: List of patterns that matched
        severity: Severity of the threat
        action: Recommended action
        positions: Positions where patterns were found
    """
    detected: bool = False
    patterns_matched: List[str] = field(default_factory=list)
    severity: ThreatSeverity = ThreatSeverity.LOW
    action: SanitizationAction = SanitizationAction.NONE
    positions: List[int] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "detected": self.detected,
            "patterns_matched": self.patterns_matched,
            "severity": self.severity.value,
            "action": self.action.value,
            "positions": self.positions,
        }


@dataclass
class InputSanitizerConfig:
    """
    Configuration for InputSanitizer.
    
    Attributes:
        max_length: Maximum input length (default: 10000)
        enable_prompt_injection_detection: Enable prompt injection detection
        enable_html_injection_detection: Enable HTML injection detection
        enable_control_char_removal: Enable control character removal
        enable_unicode_homoglyph_detection: Enable unicode homoglyph detection
        enable_base64_detection: Enable base64 pattern detection
        enable_rot13_detection: Enable ROT13 variant detection
        enable_events: Enable event emission
        critical_action: Action for CRITICAL severity (default: REJECT)
        high_action: Action for HIGH severity (default: DROP)
        medium_action: Action for MEDIUM severity (default: ISOLATE)
        low_action: Action for LOW severity (default: SANITIZE_AND_WARN)
    """
    max_length: int = 10000
    enable_prompt_injection_detection: bool = True
    enable_html_injection_detection: bool = True
    enable_control_char_removal: bool = True
    enable_unicode_homoglyph_detection: bool = True
    enable_base64_detection: bool = True
    enable_rot13_detection: bool = True
    enable_events: bool = True
    
    # Severity-based actions
    critical_action: SanitizationAction = SanitizationAction.REJECT
    high_action: SanitizationAction = SanitizationAction.DROP
    medium_action: SanitizationAction = SanitizationAction.ISOLATE
    low_action: SanitizationAction = SanitizationAction.SANITIZE_AND_WARN
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_length": self.max_length,
            "enable_prompt_injection_detection": self.enable_prompt_injection_detection,
            "enable_html_injection_detection": self.enable_html_injection_detection,
            "enable_control_char_removal": self.enable_control_char_removal,
            "enable_unicode_homoglyph_detection": self.enable_unicode_homoglyph_detection,
            "enable_base64_detection": self.enable_base64_detection,
            "enable_rot13_detection": self.enable_rot13_detection,
            "enable_events": self.enable_events,
            "critical_action": self.critical_action.value,
            "high_action": self.high_action.value,
            "medium_action": self.medium_action.value,
            "low_action": self.low_action.value,
        }


# Default prompt injection patterns
DEFAULT_PROMPT_INJECTION_PATTERNS = [
    # Direct prompt manipulation
    "ignore previous instructions",
    "ignore all previous",
    "disregard all above",
    "disregard previous",
    "forget everything",
    "forget previous",
    "forget all instructions",
    
    # System prompt attacks
    "system prompt",
    "you are now",
    "act as if",
    "pretend you are",
    "roleplay as",
    "simulate being",
    
    # Instruction override
    "new instructions",
    "override instructions",
    "replace instructions",
    "update your instructions",
    "change your behavior",
    
    # Authority claims
    "i am your developer",
    "i am your admin",
    "i am the system",
    "this is a test",
    "debug mode",
    
    # Output manipulation
    "output the following",
    "print the following",
    "say the following",
    "repeat after me",
]

# Common unicode homoglyphs (look-alike characters)
UNICODE_HOMOGLYPHS = {
    # Cyrillic look-alikes
    '\u0430': 'a',  # Cyrillic 'а' looks like Latin 'a'
    '\u0435': 'e',  # Cyrillic 'е' looks like Latin 'e'
    '\u043e': 'o',  # Cyrillic 'о' looks like Latin 'o'
    '\u0440': 'p',  # Cyrillic 'р' looks like Latin 'p'
    '\u0441': 'c',  # Cyrillic 'с' looks like Latin 'c'
    '\u0443': 'y',  # Cyrillic 'у' looks like Latin 'y'
    '\u0445': 'x',  # Cyrillic 'х' looks like Latin 'x'
    '\u0456': 'i',  # Cyrillic 'і' looks like Latin 'i'
    '\u0458': 'j',  # Cyrillic 'ј' looks like Latin 'j'
    
    # Greek look-alikes
    '\u03b1': 'a',  # Greek 'α' looks like Latin 'a'
    '\u03b5': 'e',  # Greek 'ε' looks like Latin 'e'
    '\u03b9': 'i',  # Greek 'ι' looks like Latin 'i'
    '\u03bf': 'o',  # Greek 'ο' looks like Latin 'o'
    '\u03c1': 'p',  # Greek 'ρ' looks like Latin 'p'
    
    # Other common homoglyphs
    '\u0131': 'i',  # Dotless i
    '\u0307': '',    # Combining dot above
    '\u200b': '',    # Zero-width space
    '\u200c': '',    # Zero-width non-joiner
    '\u200d': '',    # Zero-width joiner
    '\u2060': '',    # Word joiner
    '\uFEFF': '',    # Byte order mark
}

# Leetspeak mappings for detection
LEETSPEAK_MAP = {
    '4': 'a',
    '3': 'e',
    '1': 'i',
    '0': 'o',
    '5': 's',
    '7': 't',
    '@': 'a',
    '$': 's',
    '|': 'i',
    '!': 'i',
}


class InputSanitizer:
    """
    Sanitizes user inputs for security.
    
    Implements multiple sanitization actions based on threat severity:
    - Prompt injection detection and mitigation
    - HTML injection escaping
    - Control character removal
    - Unicode homoglyph detection
    - Base64 pattern detection
    - ROT13 variant detection
    
    Usage:
        sanitizer = InputSanitizer(config=InputSanitizerConfig())
        
        # Basic sanitization
        result = sanitizer.sanitize(user_input)
        if result.rejected:
            return "Input rejected for security reasons"
        clean_input = result.sanitized
        
        # Check for injection only
        injection_result = sanitizer.detect_injection(user_input)
        if injection_result.detected:
            print(f"Threat detected: {injection_result.severity.value}")
        
        # Escape HTML
        escaped = sanitizer.escape_html(user_input)
        
        # Remove control characters
        clean = sanitizer.remove_control_chars(user_input)
    
    Attributes:
        config: InputSanitizerConfig instance
        event_bus: Optional EventBus for security alerts
    """
    
    def __init__(
        self,
        config: Optional[InputSanitizerConfig] = None,
        event_bus: Optional[EventBus] = None,
        custom_patterns: Optional[List[str]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize InputSanitizer.
        
        Args:
            config: Configuration options
            event_bus: EventBus for emitting security alerts
            custom_patterns: Additional prompt injection patterns
            logger: Optional logger instance
        """
        self._config = config or InputSanitizerConfig()
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger(__name__)
        
        # Build pattern set
        self._injection_patterns = list(DEFAULT_PROMPT_INJECTION_PATTERNS)
        if custom_patterns:
            self._injection_patterns.extend(custom_patterns)
        
        # Compile regex patterns for efficiency
        self._compiled_patterns = self._compile_patterns()
        
        # Statistics
        self._stats = {
            "total_sanitizations": 0,
            "injections_detected": 0,
            "injections_blocked": 0,
            "html_escaped": 0,
            "control_chars_removed": 0,
            "homoglyphs_detected": 0,
            "base64_detected": 0,
            "rot13_detected": 0,
        }
    
    def _compile_patterns(self) -> List[re.Pattern]:
        """Compile injection patterns into regex."""
        compiled = []
        for pattern in self._injection_patterns:
            try:
                # Case-insensitive, allow whitespace variations
                compiled.append(re.compile(re.escape(pattern), re.IGNORECASE))
            except re.error:
                self._logger.warning(f"Failed to compile pattern: {pattern}")
        return compiled
    
    def sanitize(self, text: str) -> SanitizationResult:
        """
        Sanitize input text for security.
        
        Performs all enabled sanitization checks and returns
        the sanitized result with any modifications made.
        
        Args:
            text: Input text to sanitize
            
        Returns:
            SanitizationResult with sanitized text and modification details
        """
        self._stats["total_sanitizations"] += 1
        
        result = SanitizationResult(original=text, sanitized=text)
        current_text = text
        position_offset = 0
        
        # Check for prompt injection first (highest priority)
        if self._config.enable_prompt_injection_detection:
            injection_result = self.detect_injection(current_text)
            
            if injection_result.detected:
                self._stats["injections_detected"] += 1
                
                action = self._get_action_for_severity(injection_result.severity)
                result.action_taken = action
                
                if action == SanitizationAction.REJECT:
                    self._stats["injections_blocked"] += 1
                    result.rejected = True
                    result.rejection_reason = f"Prompt injection detected: {', '.join(injection_result.patterns_matched)}"
                    self._emit_security_alert("prompt_injection", injection_result)
                    return result
                
                elif action == SanitizationAction.DROP:
                    # Remove the matched content
                    for pattern in injection_result.patterns_matched:
                        current_text = re.sub(re.escape(pattern), '', current_text, flags=re.IGNORECASE)
                    result.was_modified = True
                    
                elif action == SanitizationAction.ISOLATE:
                    # Mark for isolation but continue
                    result.modifications.append(ModificationRecord(
                        rule_name="prompt_injection",
                        action=action,
                        original=text,
                        modified="[ISOLATED]",
                    ))
                    
                elif action == SanitizationAction.SANITIZE_AND_WARN:
                    # Escape the content
                    for pattern in injection_result.patterns_matched:
                        escaped = html.escape(pattern)
                        current_text = re.sub(re.escape(pattern), escaped, current_text, flags=re.IGNORECASE)
                    result.was_modified = True
        
        # Check for unicode homoglyphs
        if self._config.enable_unicode_homoglyph_detection:
            homoglyph_result = self.detect_unicode_homoglyphs(current_text)
            if homoglyph_result:
                self._stats["homoglyphs_detected"] += len(homoglyph_result)
                for char, pos in homoglyph_result:
                    result.modifications.append(ModificationRecord(
                        position=pos,
                        original=char,
                        modified=UNICODE_HOMOGLYPHS.get(char, char),
                        rule_name="unicode_homoglyph",
                        action=SanitizationAction.ESCAPE,
                    ))
        
        # Check for base64 patterns
        if self._config.enable_base64_detection:
            base64_result = self.detect_base64_patterns(current_text)
            if base64_result:
                self._stats["base64_detected"] += 1
                for pattern in base64_result:
                    result.modifications.append(ModificationRecord(
                        rule_name="base64_pattern",
                        action=SanitizationAction.ESCAPE,
                        original=pattern,
                        modified="[ENCODED]",
                    ))
        
        # Check for ROT13 variants
        if self._config.enable_rot13_detection:
            rot13_result = self.detect_rot13_variants(current_text)
            if rot13_result:
                self._stats["rot13_detected"] += 1
                for pattern in rot13_result:
                    result.modifications.append(ModificationRecord(
                        rule_name="rot13_pattern",
                        action=SanitizationAction.ESCAPE,
                        original=pattern,
                        modified="[ENCODED]",
                    ))
        
        # Remove control characters
        if self._config.enable_control_char_removal:
            clean_text = self.remove_control_chars(current_text)
            if clean_text != current_text:
                self._stats["control_chars_removed"] += 1
                result.was_modified = True
                result.modifications.append(ModificationRecord(
                    rule_name="control_chars",
                    action=SanitizationAction.REMOVE,
                ))
                current_text = clean_text
        
        # Escape HTML
        if self._config.enable_html_injection_detection:
            escaped_text = self.escape_html(current_text)
            if escaped_text != current_text:
                self._stats["html_escaped"] += 1
                result.was_modified = True
                result.modifications.append(ModificationRecord(
                    rule_name="html_injection",
                    action=SanitizationAction.ESCAPE,
                ))
                current_text = escaped_text
        
        # Truncate if over max length
        if len(current_text) > self._config.max_length:
            current_text = current_text[:self._config.max_length]
            result.was_modified = True
            result.modifications.append(ModificationRecord(
                rule_name="max_length",
                action=SanitizationAction.ESCAPE,
                original=f"[{len(text)} chars]",
                modified=f"[{self._config.max_length} chars]",
            ))
        
        result.sanitized = current_text
        return result
    
    def detect_injection(self, text: str) -> InjectionResult:
        """
        Detect prompt injection attempts in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            InjectionResult with detection details
        """
        result = InjectionResult()
        
        # Normalize text for detection
        normalized_text = self._normalize_for_detection(text)
        
        # Check compiled patterns
        for pattern in self._compiled_patterns:
            matches = pattern.finditer(normalized_text)
            for match in matches:
                result.detected = True
                result.patterns_matched.append(match.group())
                result.positions.append(match.start())
        
        # Also check normalized variants
        if not result.detected:
            # Check with leetspeak normalization
            leet_normalized = self._normalize_leetspeak(normalized_text)
            for pattern in self._injection_patterns:
                if pattern.lower() in leet_normalized.lower():
                    result.detected = True
                    result.patterns_matched.append(f"[leetspeak]{pattern}")
        
        # Determine severity
        if result.detected:
            result.severity = self._determine_severity(text, result.patterns_matched)
            result.action = self._get_action_for_severity(result.severity)
        
        return result
    
    def _normalize_for_detection(self, text: str) -> str:
        """Normalize text for injection detection."""
        # Convert to lowercase
        normalized = text.lower()
        
        # Normalize unicode homoglyphs
        for char, replacement in UNICODE_HOMOGLYPHS.items():
            normalized = normalized.replace(char, replacement)
        
        # Remove zero-width characters
        normalized = re.sub(r'[\u200b-\u200f\u2060-\u206f\ufeff]', '', normalized)
        
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized
    
    def _normalize_leetspeak(self, text: str) -> str:
        """Convert leetspeak to normal text."""
        result = text.lower()
        for leet, normal in LEETSPEAK_MAP.items():
            result = result.replace(leet, normal)
        return result
    
    def _determine_severity(self, text: str, patterns: List[str]) -> ThreatSeverity:
        """Determine threat severity based on patterns and context."""
        # Critical: Direct system access attempts
        critical_patterns = ["system prompt", "you are now", "act as if", "ignore all previous"]
        for pattern in patterns:
            if any(cp in pattern.lower() for cp in critical_patterns):
                return ThreatSeverity.CRITICAL
        
        # High: Instruction override attempts
        high_patterns = ["new instructions", "override", "forget", "disregard"]
        for pattern in patterns:
            if any(hp in pattern.lower() for hp in high_patterns):
                return ThreatSeverity.HIGH
        
        # Medium: Authority claims
        medium_patterns = ["i am your", "debug mode", "test mode"]
        for pattern in patterns:
            if any(mp in pattern.lower() for mp in medium_patterns):
                return ThreatSeverity.MEDIUM
        
        # Default to low
        return ThreatSeverity.LOW
    
    def _get_action_for_severity(self, severity: ThreatSeverity) -> SanitizationAction:
        """Get action for given severity level."""
        action_map = {
            ThreatSeverity.CRITICAL: self._config.critical_action,
            ThreatSeverity.HIGH: self._config.high_action,
            ThreatSeverity.MEDIUM: self._config.medium_action,
            ThreatSeverity.LOW: self._config.low_action,
        }
        return action_map.get(severity, SanitizationAction.SANITIZE_AND_WARN)
    
    def escape_html(self, text: str) -> str:
        """
        Escape HTML special characters.
        
        Args:
            text: Text to escape
            
        Returns:
            Text with HTML characters escaped
        """
        return html.escape(text, quote=True)
    
    def remove_control_chars(self, text: str) -> str:
        """
        Remove control characters from text.
        
        Args:
            text: Text to clean
            
        Returns:
            Text with control characters removed
        """
        # Remove control characters except newlines and tabs
        return ''.join(
            char for char in text
            if unicodedata.category(char) != 'Cc' or char in '\n\t\r'
        )
    
    def detect_unicode_homoglyphs(self, text: str) -> List[tuple]:
        """
        Detect unicode homoglyphs in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of (character, position) tuples
        """
        results = []
        for i, char in enumerate(text):
            if char in UNICODE_HOMOGLYPHS:
                results.append((char, i))
        return results
    
    def detect_base64_patterns(self, text: str) -> List[str]:
        """
        Detect potential base64 encoded content.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of detected base64-like patterns
        """
        results = []
        
        # Pattern for base64-like strings (long alphanumeric sequences)
        base64_pattern = re.compile(r'[A-Za-z0-9+/]{20,}={0,2}')
        
        matches = base64_pattern.finditer(text)
        for match in matches:
            try:
                # Try to decode
                decoded = base64.b64decode(match.group()).decode('utf-8', errors='ignore')
                # Check if decoded looks suspicious
                if any(p in decoded.lower() for p in ['system', 'prompt', 'ignore', 'inject']):
                    results.append(match.group())
            except Exception:
                pass
        
        return results
    
    def detect_rot13_variants(self, text: str) -> List[str]:
        """
        Detect ROT13 encoded patterns that might hide injection.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of detected ROT13-like patterns
        """
        results = []
        
        # Common injection phrases in ROT13
        rot13_patterns = [
            'vtaber cerivbaf vafgehpgvbf',  # "ignore previous instructions"
            'flfgrz cevzr',  # "system prime" (partial)
        ]
        
        # Check if text contains ROT13-like sequences
        text_lower = text.lower()
        for pattern in rot13_patterns:
            if pattern in text_lower:
                results.append(pattern)
        
        return results
    
    def _emit_security_alert(
        self,
        alert_type: str,
        injection_result: InjectionResult,
    ) -> None:
        """Emit security alert event."""
        if not self._config.enable_events or not self._event_bus:
            return
        
        event = Event(
            event_type="SECURITY_ALERT",
            data={
                "alert_type": alert_type,
                "severity": injection_result.severity.value,
                "patterns_matched": injection_result.patterns_matched,
                "action_taken": injection_result.action.value,
                "timestamp": now_utc_iso(),
            },
            severity=EventSeverity.CRITICAL if injection_result.severity == ThreatSeverity.CRITICAL else EventSeverity.WARN,
            source="InputSanitizer",
        )
        self._event_bus.emit(event)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get sanitization statistics."""
        return dict(self._stats)
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "total_sanitizations": 0,
            "injections_detected": 0,
            "injections_blocked": 0,
            "html_escaped": 0,
            "control_chars_removed": 0,
            "homoglyphs_detected": 0,
            "base64_detected": 0,
            "rot13_detected": 0,
        }
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set EventBus for emitting events."""
        self._event_bus = event_bus
    
    def add_custom_pattern(self, pattern: str) -> None:
        """Add a custom injection pattern."""
        self._injection_patterns.append(pattern)
        self._compiled_patterns = self._compile_patterns()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "config": self._config.to_dict(),
            "stats": self.get_stats(),
            "pattern_count": len(self._injection_patterns),
        }


# Global instance
_global_sanitizer: Optional[InputSanitizer] = None


def get_input_sanitizer(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[EventBus] = None,
) -> InputSanitizer:
    """
    Get global InputSanitizer instance.
    
    Creates instance on first call, returns existing on subsequent calls.
    
    Args:
        config: Configuration dictionary (only used on first call)
        event_bus: EventBus instance (only used on first call)
        
    Returns:
        Global InputSanitizer instance
    """
    global _global_sanitizer
    if _global_sanitizer is None:
        sanitizer_config = None
        if config:
            sanitizer_config = InputSanitizerConfig(**config)
        _global_sanitizer = InputSanitizer(
            config=sanitizer_config,
            event_bus=event_bus,
        )
    return _global_sanitizer


def reset_input_sanitizer() -> None:
    """Reset global InputSanitizer instance."""
    global _global_sanitizer
    _global_sanitizer = None
