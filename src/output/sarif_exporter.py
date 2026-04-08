"""
SARIF Output Format for GitHub Code Scanning Integration.

ITEM-PROD-01: SARIF Output Format for TITAN Protocol v4.0.0

Implements SARIF 2.1.0 schema for exporting gate results to GitHub Code Scanning.
Maps gate severities to SARIF levels for proper alert categorization.

Author: TITAN FUSE Team
Version: 4.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json
import os

# Import version from VERSION file
def _get_version() -> str:
    """Get TITAN Protocol version."""
    try:
        version_file = os.path.join(os.path.dirname(__file__), "..", "..", "VERSION")
        with open(version_file, "r") as f:
            return f.read().strip().split("\n")[0]
    except Exception:
        return "4.0.0"


# =============================================================================
# Severity Mapping
# =============================================================================

class SARIFLevel(Enum):
    """
    SARIF result level enumeration.
    
    Maps to SARIF 2.1.0 level values:
    - error: A problem that should be addressed
    - warning: A potential problem
    - note: An informational result
    - none: A result that is not classified
    """
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"
    NONE = "none"


def map_severity_to_sarif(severity: str) -> SARIFLevel:
    """
    Map TITAN gate severity to SARIF level.
    
    Severity mapping per requirements:
    - SEV-1 -> "error" (Critical - blocks release)
    - SEV-2 -> "error" (High - should be fixed)
    - SEV-3 -> "warning" (Medium - nice to fix)
    - SEV-4 -> "note" (Low - minor issue)
    
    Args:
        severity: Severity string (e.g., "SEV-1", "SEV-2", etc.)
        
    Returns:
        SARIFLevel enum value
        
    Examples:
        >>> map_severity_to_sarif("SEV-1")
        <SARIFLevel.ERROR: 'error'>
        >>> map_severity_to_sarif("SEV-3")
        <SARIFLevel.WARNING: 'warning'>
    """
    severity_map = {
        "SEV-1": SARIFLevel.ERROR,
        "SEV-2": SARIFLevel.ERROR,
        "SEV-3": SARIFLevel.WARNING,
        "SEV-4": SARIFLevel.NOTE,
        # Also support lowercase and alternate formats
        "sev-1": SARIFLevel.ERROR,
        "sev-2": SARIFLevel.ERROR,
        "sev-3": SARIFLevel.WARNING,
        "sev-4": SARIFLevel.NOTE,
        "SEV_1": SARIFLevel.ERROR,
        "SEV_2": SARIFLevel.ERROR,
        "SEV_3": SARIFLevel.WARNING,
        "SEV_4": SARIFLevel.NOTE,
    }
    return severity_map.get(severity, SARIFLevel.NONE)


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class SARIFLocation:
    """
    Represents a location in SARIF format.
    
    Attributes:
        uri: URI of the file (relative or absolute)
        start_line: Starting line number (1-indexed)
        end_line: Ending line number (optional)
        start_column: Starting column (optional)
        end_column: Ending column (optional)
    """
    uri: str
    start_line: int = 1
    end_line: Optional[int] = None
    start_column: Optional[int] = None
    end_column: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to SARIF location format."""
        physical_location = {
            "artifactLocation": {
                "uri": self.uri
            }
        }
        
        region = {"startLine": self.start_line}
        if self.end_line is not None:
            region["endLine"] = self.end_line
        if self.start_column is not None:
            region["startColumn"] = self.start_column
        if self.end_column is not None:
            region["endColumn"] = self.end_column
            
        physical_location["region"] = region
        
        return {"physicalLocation": physical_location}


@dataclass
class SARIFResult:
    """
    Represents a single result in SARIF format.
    
    Attributes:
        rule_id: Identifier of the rule that was violated
        level: SARIF level (error, warning, note, none)
        message: Human-readable message describing the result
        locations: List of locations where the result was found
        details: Additional details as a dictionary
    """
    rule_id: str
    level: SARIFLevel
    message: str
    locations: List[SARIFLocation] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to SARIF result format."""
        result = {
            "ruleId": self.rule_id,
            "level": self.level.value,
            "message": {
                "text": self.message
            }
        }
        
        if self.locations:
            result["locations"] = [loc.to_dict() for loc in self.locations]
            
        # Add additional properties
        if self.details:
            result["properties"] = self.details
            
        return result


@dataclass
class SARIFRule:
    """
    Represents a rule definition in SARIF format.
    
    Attributes:
        id: Unique rule identifier
        name: Short rule name
        description: Full rule description
        default_level: Default SARIF level for violations
        help_uri: URL to rule documentation
    """
    id: str
    name: str
    description: str = ""
    default_level: SARIFLevel = SARIFLevel.WARNING
    help_uri: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to SARIF rule format."""
        rule = {
            "id": self.id,
            "name": self.name,
            "shortDescription": {
                "text": self.description or self.name
            }
        }
        
        if self.default_level != SARIFLevel.WARNING:
            rule["defaultConfiguration"] = {
                "level": self.default_level.value
            }
            
        if self.help_uri:
            rule["helpUri"] = self.help_uri
            
        return rule


@dataclass
class SARIFRun:
    """
    Represents a single run in SARIF format.
    
    A run contains results from a single execution of a tool.
    
    Attributes:
        tool_name: Name of the analysis tool
        tool_version: Version of the analysis tool
        results: List of results from this run
        rules: Dictionary of rule definitions (rule_id -> SARIFRule)
        invocation: Invocation information
    """
    tool_name: str
    tool_version: str
    results: List[SARIFResult] = field(default_factory=list)
    rules: Dict[str, SARIFRule] = field(default_factory=dict)
    invocation: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to SARIF run format."""
        run = {
            "tool": {
                "driver": {
                    "name": self.tool_name,
                    "version": self.tool_version,
                    "informationUri": "https://github.com/titan-protocol/titan",
                    "rules": [rule.to_dict() for rule in self.rules.values()]
                }
            },
            "results": [result.to_dict() for result in self.results]
        }
        
        if self.invocation:
            run["invocations"] = [self.invocation]
            
        return run


@dataclass
class SARIFReport:
    """
    Complete SARIF 2.1.0 report.
    
    The top-level SARIF object containing schema, version, and runs.
    
    Attributes:
        runs: List of runs included in this report
        schema_uri: URI to the SARIF schema
        version: SARIF schema version
    """
    runs: List[SARIFRun] = field(default_factory=list)
    schema_uri: str = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
    version: str = "2.1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to complete SARIF report format."""
        return {
            "$schema": self.schema_uri,
            "version": self.version,
            "runs": [run.to_dict() for run in self.runs]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SARIFReport":
        """Create SARIFReport from dictionary."""
        runs = []
        
        for run_data in data.get("runs", []):
            tool_info = run_data.get("tool", {}).get("driver", {})
            
            # Parse rules
            rules = {}
            for rule_data in tool_info.get("rules", []):
                rule = SARIFRule(
                    id=rule_data["id"],
                    name=rule_data.get("name", rule_data["id"]),
                    description=rule_data.get("shortDescription", {}).get("text", ""),
                    default_level=SARIFLevel(
                        rule_data.get("defaultConfiguration", {}).get("level", "warning")
                    ),
                    help_uri=rule_data.get("helpUri")
                )
                rules[rule.id] = rule
            
            # Parse results
            results = []
            for result_data in run_data.get("results", []):
                locations = []
                for loc_data in result_data.get("locations", []):
                    phys_loc = loc_data.get("physicalLocation", {})
                    artifact_loc = phys_loc.get("artifactLocation", {})
                    region = phys_loc.get("region", {})
                    
                    location = SARIFLocation(
                        uri=artifact_loc.get("uri", ""),
                        start_line=region.get("startLine", 1),
                        end_line=region.get("endLine"),
                        start_column=region.get("startColumn"),
                        end_column=region.get("endColumn")
                    )
                    locations.append(location)
                
                result = SARIFResult(
                    rule_id=result_data["ruleId"],
                    level=SARIFLevel(result_data.get("level", "none")),
                    message=result_data.get("message", {}).get("text", ""),
                    locations=locations,
                    details=result_data.get("properties", {})
                )
                results.append(result)
            
            run = SARIFRun(
                tool_name=tool_info.get("name", "Unknown"),
                tool_version=tool_info.get("version", "0.0.0"),
                results=results,
                rules=rules
            )
            runs.append(run)
        
        return cls(
            runs=runs,
            schema_uri=data.get("$schema", cls.schema_uri),
            version=data.get("version", cls.version)
        )


# =============================================================================
# GateResult Type (for typing support)
# =============================================================================

@dataclass
class GateResult:
    """
    Gate result for SARIF export.
    
    This represents a gate evaluation result that can be exported to SARIF.
    Compatible with the existing gate result structures in the codebase.
    
    Attributes:
        gate_id: Identifier for the gate
        gate_name: Human-readable gate name
        result: Result of the gate (PASS, FAIL, ADVISORY_PASS, etc.)
        severity: Severity level (SEV-1, SEV-2, SEV-3, SEV-4)
        message: Human-readable message
        source_file: Source file path if applicable
        line_start: Starting line number
        line_end: Ending line number
        details: Additional details
        timestamp: When the result was generated
    """
    gate_id: str
    gate_name: str
    result: str  # PASS, FAIL, ADVISORY_PASS, etc.
    severity: str  # SEV-1, SEV-2, SEV-3, SEV-4
    message: str = ""
    source_file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "gate_id": self.gate_id,
            "gate_name": self.gate_name,
            "result": self.result,
            "severity": self.severity,
            "message": self.message,
            "source_file": self.source_file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "details": self.details,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_gap(cls, gap: Any) -> "GateResult":
        """
        Create GateResult from Gap object.
        
        Args:
            gap: Gap object from src.state.gap
            
        Returns:
            GateResult instance
        """
        return cls(
            gate_id=gap.id,
            gate_name=f"Gap: {gap.reason[:50]}",
            result="FAIL",
            severity=gap.severity.value if hasattr(gap.severity, 'value') else str(gap.severity),
            message=gap.reason,
            source_file=gap.source_file,
            line_start=gap.source_line_start,
            line_end=gap.source_line_end,
            details={
                "context": gap.context,
                "suggested_action": gap.suggested_action,
                "tags": gap.tags,
                "verified": gap.verified
            }
        )


# =============================================================================
# SARIF Exporter
# =============================================================================

class SARIFExporter:
    """
    SARIF Exporter for GitHub Code Scanning integration.
    
    Exports gate results to SARIF 2.1.0 format compatible with GitHub Code Scanning.
    Implements severity mapping from TITAN gates to SARIF levels.
    
    Example:
        >>> exporter = SARIFExporter()
        >>> results = [
        ...     GateResult(
        ...         gate_id="GATE-001",
        ...         gate_name="Security Check",
        ...         result="FAIL",
        ...         severity="SEV-1",
        ...         message="SQL injection vulnerability detected"
        ...     )
        ... ]
        >>> report = exporter.export(results)
        >>> json_output = exporter.to_json(report)
    """
    
    TOOL_NAME = "TITAN Protocol"
    
    def __init__(self, version: Optional[str] = None, repository_root: Optional[str] = None):
        """
        Initialize SARIF exporter.
        
        Args:
            version: TITAN Protocol version (defaults to reading from VERSION file)
            repository_root: Root directory of repository for relative paths
        """
        self.version = version or _get_version()
        self.repository_root = repository_root or os.getcwd()
        self._rules: Dict[str, SARIFRule] = {}
        
    def export(self, results: List[GateResult], 
               run_name: Optional[str] = None,
               additional_properties: Optional[Dict[str, Any]] = None) -> SARIFReport:
        """
        Export gate results to SARIF report.
        
        Args:
            results: List of GateResult objects to export
            run_name: Optional name for this run
            additional_properties: Additional properties to include
            
        Returns:
            SARIFReport containing the exported results
        """
        # Create rules from results
        rules: Dict[str, SARIFRule] = {}
        sarif_results: List[SARIFResult] = []
        
        for gate_result in results:
            # Skip passed gates by default
            if gate_result.result == "PASS":
                continue
                
            # Get or create rule
            rule_id = gate_result.gate_id
            if rule_id not in rules:
                sarif_level = map_severity_to_sarif(gate_result.severity)
                rule = SARIFRule(
                    id=rule_id,
                    name=gate_result.gate_name,
                    description=f"TITAN Protocol gate: {gate_result.gate_name}",
                    default_level=sarif_level,
                    help_uri=f"https://titan-protocol.io/rules/{rule_id}"
                )
                rules[rule_id] = rule
            
            # Create location if source file is specified
            locations: List[SARIFLocation] = []
            if gate_result.source_file:
                # Make path relative to repository root
                uri = gate_result.source_file
                if self.repository_root and os.path.isabs(uri):
                    try:
                        uri = os.path.relpath(uri, self.repository_root)
                    except ValueError:
                        # Different drives on Windows
                        pass
                
                location = SARIFLocation(
                    uri=uri,
                    start_line=gate_result.line_start or 1,
                    end_line=gate_result.line_end
                )
                locations.append(location)
            
            # Determine SARIF level
            sarif_level = map_severity_to_sarif(gate_result.severity)
            
            # Create result
            result_details = dict(gate_result.details)
            result_details["timestamp"] = gate_result.timestamp
            result_details["gate_result"] = gate_result.result
            
            if additional_properties:
                result_details.update(additional_properties)
            
            sarif_result = SARIFResult(
                rule_id=rule_id,
                level=sarif_level,
                message=gate_result.message or f"Gate '{gate_result.gate_name}' failed",
                locations=locations,
                details=result_details
            )
            sarif_results.append(sarif_result)
        
        # Create invocation info
        invocation = {
            "executionSuccessful": True,
            "startTimeUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
        
        if run_name:
            invocation["commandLine"] = run_name
        
        # Create run
        run = SARIFRun(
            tool_name=self.TOOL_NAME,
            tool_version=self.version,
            results=sarif_results,
            rules=rules,
            invocation=invocation
        )
        
        # Create report
        report = SARIFReport(runs=[run])
        
        return report
    
    def to_json(self, report: SARIFReport, indent: int = 2) -> str:
        """
        Convert SARIF report to JSON string.
        
        Args:
            report: SARIFReport to convert
            indent: JSON indentation level (default: 2)
            
        Returns:
            JSON string representation of the report
        """
        return json.dumps(report.to_dict(), indent=indent, ensure_ascii=False)
    
    def export_to_file(self, results: List[GateResult], 
                       output_path: str,
                       run_name: Optional[str] = None,
                       additional_properties: Optional[Dict[str, Any]] = None) -> str:
        """
        Export gate results directly to a file.
        
        Args:
            results: List of GateResult objects to export
            output_path: Path to output file
            run_name: Optional name for this run
            additional_properties: Additional properties to include
            
        Returns:
            Path to the output file
        """
        report = self.export(results, run_name, additional_properties)
        json_output = self.to_json(report)
        
        # Ensure directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_output)
            
        return output_path
    
    def from_gate_manager_result(self, manager_result: Any) -> List[GateResult]:
        """
        Convert GateManagerResult to list of GateResult objects.
        
        Args:
            manager_result: GateManagerResult from gate_manager.py
            
        Returns:
            List of GateResult objects
        """
        results: List[GateResult] = []
        
        # Process pre-exec results
        if hasattr(manager_result, 'pre_exec_results'):
            for check_result in manager_result.pre_exec_results:
                gate_result = GateResult(
                    gate_id=check_result.gate_name,
                    gate_name=check_result.gate_name,
                    result=check_result.result.value if hasattr(check_result.result, 'value') else str(check_result.result),
                    severity=check_result.details.get("severity", "SEV-3") if hasattr(check_result, 'details') else "SEV-3",
                    message=check_result.message,
                    details=check_result.details if hasattr(check_result, 'details') else {}
                )
                results.append(gate_result)
        
        # Process post-exec results
        if hasattr(manager_result, 'post_exec_results'):
            for check_result in manager_result.post_exec_results:
                gate_result = GateResult(
                    gate_id=check_result.gate_name,
                    gate_name=check_result.gate_name,
                    result=check_result.result.value if hasattr(check_result.result, 'value') else str(check_result.result),
                    severity=check_result.details.get("severity", "SEV-3") if hasattr(check_result, 'details') else "SEV-3",
                    message=check_result.message,
                    details=check_result.details if hasattr(check_result, 'details') else {}
                )
                results.append(gate_result)
        
        return results
    
    def from_gaps(self, gaps: List[Any]) -> List[GateResult]:
        """
        Convert Gap objects to GateResult objects.
        
        Args:
            gaps: List of Gap objects from src.state.gap
            
        Returns:
            List of GateResult objects
        """
        return [GateResult.from_gap(gap) for gap in gaps]


# =============================================================================
# Convenience Functions
# =============================================================================

def export_sarif(results: List[GateResult], 
                 output_path: Optional[str] = None,
                 version: Optional[str] = None) -> SARIFReport:
    """
    Convenience function to export gate results to SARIF.
    
    Args:
        results: List of GateResult objects
        output_path: Optional path to write JSON output
        version: TITAN Protocol version
        
    Returns:
        SARIFReport
    """
    exporter = SARIFExporter(version=version)
    report = exporter.export(results)
    
    if output_path:
        exporter.to_json(report)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(exporter.to_json(report))
    
    return report


def gaps_to_sarif(gaps: List[Any], 
                  output_path: Optional[str] = None,
                  version: Optional[str] = None) -> SARIFReport:
    """
    Convenience function to export Gap objects to SARIF.
    
    Args:
        gaps: List of Gap objects
        output_path: Optional path to write JSON output
        version: TITAN Protocol version
        
    Returns:
        SARIFReport
    """
    exporter = SARIFExporter(version=version)
    results = exporter.from_gaps(gaps)
    return export_sarif(results, output_path, version)
