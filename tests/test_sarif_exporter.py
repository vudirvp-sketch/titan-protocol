"""
Tests for SARIF Output Format.

ITEM-PROD-01: SARIF Output Format for TITAN Protocol v4.0.0

Tests SARIF exporter functionality including:
- Severity mapping (SEV-1 to SEV-4)
- SARIF 2.1.0 schema compliance
- JSON output format
- GitHub Code Scanning compatibility
"""

import json
import os
import tempfile
import unittest
from datetime import datetime

from src.output.sarif_exporter import (
    SARIFExporter,
    SARIFReport,
    SARIFRun,
    SARIFResult,
    SARIFRule,
    SARIFLocation,
    SARIFLevel,
    GateResult,
    map_severity_to_sarif,
    export_sarif,
    gaps_to_sarif,
)


class TestSARIFLevel(unittest.TestCase):
    """Tests for SARIFLevel enum."""
    
    def test_level_values(self):
        """Test that SARIF levels have correct values."""
        self.assertEqual(SARIFLevel.ERROR.value, "error")
        self.assertEqual(SARIFLevel.WARNING.value, "warning")
        self.assertEqual(SARIFLevel.NOTE.value, "note")
        self.assertEqual(SARIFLevel.NONE.value, "none")


class TestMapSeverityToSARIF(unittest.TestCase):
    """Tests for severity to SARIF level mapping."""
    
    def test_sev1_maps_to_error(self):
        """SEV-1 should map to error."""
        self.assertEqual(map_severity_to_sarif("SEV-1"), SARIFLevel.ERROR)
    
    def test_sev2_maps_to_error(self):
        """SEV-2 should map to error."""
        self.assertEqual(map_severity_to_sarif("SEV-2"), SARIFLevel.ERROR)
    
    def test_sev3_maps_to_warning(self):
        """SEV-3 should map to warning."""
        self.assertEqual(map_severity_to_sarif("SEV-3"), SARIFLevel.WARNING)
    
    def test_sev4_maps_to_note(self):
        """SEV-4 should map to note."""
        self.assertEqual(map_severity_to_sarif("SEV-4"), SARIFLevel.NOTE)
    
    def test_lowercase_severity(self):
        """Lowercase severity should work."""
        self.assertEqual(map_severity_to_sarif("sev-1"), SARIFLevel.ERROR)
        self.assertEqual(map_severity_to_sarif("sev-3"), SARIFLevel.WARNING)
    
    def test_underscore_format(self):
        """Underscore format should work."""
        self.assertEqual(map_severity_to_sarif("SEV_1"), SARIFLevel.ERROR)
        self.assertEqual(map_severity_to_sarif("SEV_4"), SARIFLevel.NOTE)
    
    def test_unknown_severity_maps_to_none(self):
        """Unknown severity should map to none."""
        self.assertEqual(map_severity_to_sarif("UNKNOWN"), SARIFLevel.NONE)
        self.assertEqual(map_severity_to_sarif(""), SARIFLevel.NONE)


class TestSARIFLocation(unittest.TestCase):
    """Tests for SARIFLocation dataclass."""
    
    def test_basic_location(self):
        """Test basic location creation."""
        loc = SARIFLocation(uri="src/main.py", start_line=10)
        result = loc.to_dict()
        
        self.assertEqual(result["physicalLocation"]["artifactLocation"]["uri"], "src/main.py")
        self.assertEqual(result["physicalLocation"]["region"]["startLine"], 10)
    
    def test_location_with_end_line(self):
        """Test location with end line."""
        loc = SARIFLocation(uri="test.py", start_line=10, end_line=20)
        result = loc.to_dict()
        
        self.assertEqual(result["physicalLocation"]["region"]["endLine"], 20)
    
    def test_location_with_columns(self):
        """Test location with column information."""
        loc = SARIFLocation(
            uri="app.py",
            start_line=5,
            start_column=10,
            end_column=20
        )
        result = loc.to_dict()
        
        self.assertEqual(result["physicalLocation"]["region"]["startColumn"], 10)
        self.assertEqual(result["physicalLocation"]["region"]["endColumn"], 20)


class TestSARIFResult(unittest.TestCase):
    """Tests for SARIFResult dataclass."""
    
    def test_basic_result(self):
        """Test basic result creation."""
        result = SARIFResult(
            rule_id="GATE-001",
            level=SARIFLevel.ERROR,
            message="Security vulnerability detected"
        )
        data = result.to_dict()
        
        self.assertEqual(data["ruleId"], "GATE-001")
        self.assertEqual(data["level"], "error")
        self.assertEqual(data["message"]["text"], "Security vulnerability detected")
    
    def test_result_with_location(self):
        """Test result with location."""
        loc = SARIFLocation(uri="file.py", start_line=1)
        result = SARIFResult(
            rule_id="RULE-001",
            level=SARIFLevel.WARNING,
            message="Test warning",
            locations=[loc]
        )
        data = result.to_dict()
        
        self.assertIn("locations", data)
        self.assertEqual(len(data["locations"]), 1)
    
    def test_result_with_details(self):
        """Test result with additional details."""
        result = SARIFResult(
            rule_id="RULE-001",
            level=SARIFLevel.NOTE,
            message="Test note",
            details={"confidence": "HIGH", "category": "security"}
        )
        data = result.to_dict()
        
        self.assertIn("properties", data)
        self.assertEqual(data["properties"]["confidence"], "HIGH")


class TestSARIFRule(unittest.TestCase):
    """Tests for SARIFRule dataclass."""
    
    def test_basic_rule(self):
        """Test basic rule creation."""
        rule = SARIFRule(
            id="RULE-001",
            name="Test Rule",
            description="A test rule"
        )
        data = rule.to_dict()
        
        self.assertEqual(data["id"], "RULE-001")
        self.assertEqual(data["name"], "Test Rule")
        self.assertEqual(data["shortDescription"]["text"], "A test rule")
    
    def test_rule_with_help_uri(self):
        """Test rule with help URI."""
        rule = SARIFRule(
            id="RULE-002",
            name="Security Rule",
            help_uri="https://docs.example.com/rules/RULE-002"
        )
        data = rule.to_dict()
        
        self.assertEqual(data["helpUri"], "https://docs.example.com/rules/RULE-002")
    
    def test_rule_with_custom_level(self):
        """Test rule with custom default level."""
        rule = SARIFRule(
            id="RULE-003",
            name="Critical Rule",
            default_level=SARIFLevel.ERROR
        )
        data = rule.to_dict()
        
        self.assertIn("defaultConfiguration", data)
        self.assertEqual(data["defaultConfiguration"]["level"], "error")


class TestSARIFRun(unittest.TestCase):
    """Tests for SARIFRun dataclass."""
    
    def test_basic_run(self):
        """Test basic run creation."""
        run = SARIFRun(
            tool_name="TITAN Protocol",
            tool_version="4.0.0"
        )
        data = run.to_dict()
        
        self.assertEqual(data["tool"]["driver"]["name"], "TITAN Protocol")
        self.assertEqual(data["tool"]["driver"]["version"], "4.0.0")
        self.assertEqual(data["results"], [])
    
    def test_run_with_results(self):
        """Test run with results."""
        result = SARIFResult(
            rule_id="RULE-001",
            level=SARIFLevel.ERROR,
            message="Test error"
        )
        run = SARIFRun(
            tool_name="TITAN Protocol",
            tool_version="4.0.0",
            results=[result]
        )
        data = run.to_dict()
        
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["ruleId"], "RULE-001")
    
    def test_run_with_rules(self):
        """Test run with rule definitions."""
        rule = SARIFRule(id="RULE-001", name="Test Rule")
        run = SARIFRun(
            tool_name="TITAN Protocol",
            tool_version="4.0.0",
            rules={"RULE-001": rule}
        )
        data = run.to_dict()
        
        self.assertIn("rules", data["tool"]["driver"])
        self.assertEqual(len(data["tool"]["driver"]["rules"]), 1)


class TestSARIFReport(unittest.TestCase):
    """Tests for SARIFReport dataclass."""
    
    def test_basic_report(self):
        """Test basic report creation."""
        report = SARIFReport()
        data = report.to_dict()
        
        self.assertIn("$schema", data)
        self.assertEqual(data["version"], "2.1.0")
        self.assertIn("runs", data)
    
    def test_report_schema(self):
        """Test report has correct SARIF schema."""
        report = SARIFReport()
        data = report.to_dict()
        
        expected_schema = (
            "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
            "master/Schemata/sarif-schema-2.1.0.json"
        )
        self.assertEqual(data["$schema"], expected_schema)
    
    def test_report_with_runs(self):
        """Test report with runs."""
        run = SARIFRun(tool_name="TITAN Protocol", tool_version="4.0.0")
        report = SARIFReport(runs=[run])
        data = report.to_dict()
        
        self.assertEqual(len(data["runs"]), 1)
    
    def test_report_from_dict(self):
        """Test creating report from dictionary."""
        data = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "TITAN Protocol",
                        "version": "4.0.0",
                        "rules": []
                    }
                },
                "results": []
            }]
        }
        
        report = SARIFReport.from_dict(data)
        
        self.assertEqual(len(report.runs), 1)
        self.assertEqual(report.runs[0].tool_name, "TITAN Protocol")


class TestGateResult(unittest.TestCase):
    """Tests for GateResult dataclass."""
    
    def test_basic_gate_result(self):
        """Test basic gate result creation."""
        result = GateResult(
            gate_id="GATE-001",
            gate_name="Security Check",
            result="FAIL",
            severity="SEV-1",
            message="SQL injection detected"
        )
        
        self.assertEqual(result.gate_id, "GATE-001")
        self.assertEqual(result.severity, "SEV-1")
        self.assertEqual(result.result, "FAIL")
    
    def test_gate_result_to_dict(self):
        """Test gate result serialization."""
        result = GateResult(
            gate_id="GATE-002",
            gate_name="Test Gate",
            result="PASS",
            severity="SEV-4",
            message="All checks passed"
        )
        data = result.to_dict()
        
        self.assertEqual(data["gate_id"], "GATE-002")
        self.assertEqual(data["severity"], "SEV-4")
    
    def test_gate_result_with_location(self):
        """Test gate result with source location."""
        result = GateResult(
            gate_id="GATE-003",
            gate_name="Code Quality",
            result="FAIL",
            severity="SEV-3",
            message="Complex method detected",
            source_file="src/main.py",
            line_start=100,
            line_end=150
        )
        
        self.assertEqual(result.source_file, "src/main.py")
        self.assertEqual(result.line_start, 100)
        self.assertEqual(result.line_end, 150)
    
    def test_gate_result_timestamp(self):
        """Test gate result has timestamp."""
        result = GateResult(
            gate_id="GATE-004",
            gate_name="Test",
            result="FAIL",
            severity="SEV-1"
        )
        
        self.assertIsNotNone(result.timestamp)
        # Should be ISO 8601 format
        datetime.fromisoformat(result.timestamp.replace("Z", "+00:00"))


class TestSARIFExporter(unittest.TestCase):
    """Tests for SARIFExporter class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.exporter = SARIFExporter(version="4.0.0")
    
    def test_exporter_initialization(self):
        """Test exporter initialization."""
        self.assertEqual(self.exporter.version, "4.0.0")
        self.assertEqual(self.exporter.TOOL_NAME, "TITAN Protocol")
    
    def test_export_empty_results(self):
        """Test exporting empty results."""
        report = self.exporter.export([])
        
        self.assertIsInstance(report, SARIFReport)
        self.assertEqual(len(report.runs), 1)
        self.assertEqual(len(report.runs[0].results), 0)
    
    def test_export_single_result(self):
        """Test exporting single result."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Security Gate",
                result="FAIL",
                severity="SEV-1",
                message="Critical security issue"
            )
        ]
        
        report = self.exporter.export(results)
        
        self.assertEqual(len(report.runs[0].results), 1)
        self.assertEqual(report.runs[0].results[0].level, SARIFLevel.ERROR)
    
    def test_export_passes_filter(self):
        """Test that PASS results are filtered by default."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Passed Gate",
                result="PASS",
                severity="SEV-4",
                message="All good"
            ),
            GateResult(
                gate_id="GATE-002",
                gate_name="Failed Gate",
                result="FAIL",
                severity="SEV-2",
                message="Issue found"
            )
        ]
        
        report = self.exporter.export(results)
        
        # Only the failed result should be in the report
        self.assertEqual(len(report.runs[0].results), 1)
        self.assertEqual(report.runs[0].results[0].rule_id, "GATE-002")
    
    def test_export_severity_mapping(self):
        """Test that severities are mapped correctly."""
        test_cases = [
            ("SEV-1", SARIFLevel.ERROR),
            ("SEV-2", SARIFLevel.ERROR),
            ("SEV-3", SARIFLevel.WARNING),
            ("SEV-4", SARIFLevel.NOTE),
        ]
        
        for severity, expected_level in test_cases:
            results = [
                GateResult(
                    gate_id=f"GATE-{severity}",
                    gate_name=f"Gate {severity}",
                    result="FAIL",
                    severity=severity,
                    message=f"Test {severity}"
                )
            ]
            
            report = self.exporter.export(results)
            self.assertEqual(
                report.runs[0].results[0].level, 
                expected_level,
                f"Severity {severity} should map to {expected_level}"
            )
    
    def test_export_with_source_file(self):
        """Test exporting with source file location."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="File Gate",
                result="FAIL",
                severity="SEV-2",
                message="Issue in file",
                source_file="src/module/code.py",
                line_start=50,
                line_end=60
            )
        ]
        
        report = self.exporter.export(results)
        
        result = report.runs[0].results[0]
        self.assertEqual(len(result.locations), 1)
        self.assertEqual(result.locations[0].uri, "src/module/code.py")
        self.assertEqual(result.locations[0].start_line, 50)
        self.assertEqual(result.locations[0].end_line, 60)
    
    def test_to_json(self):
        """Test JSON output."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test Gate",
                result="FAIL",
                severity="SEV-1",
                message="Test message"
            )
        ]
        
        report = self.exporter.export(results)
        json_output = self.exporter.to_json(report)
        
        # Should be valid JSON
        data = json.loads(json_output)
        
        self.assertIn("$schema", data)
        self.assertIn("version", data)
        self.assertIn("runs", data)
    
    def test_to_json_schema_compliance(self):
        """Test JSON output schema compliance."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test Gate",
                result="FAIL",
                severity="SEV-1",
                message="Test message"
            )
        ]
        
        report = self.exporter.export(results)
        json_output = self.exporter.to_json(report)
        data = json.loads(json_output)
        
        # Verify required SARIF 2.1.0 structure
        self.assertEqual(data["version"], "2.1.0")
        self.assertIn("runs", data)
        self.assertIsInstance(data["runs"], list)
        
        run = data["runs"][0]
        self.assertIn("tool", run)
        self.assertIn("driver", run["tool"])
        self.assertIn("name", run["tool"]["driver"])
        self.assertIn("version", run["tool"]["driver"])
        self.assertIn("results", run)
    
    def test_export_to_file(self):
        """Test exporting to file."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test Gate",
                result="FAIL",
                severity="SEV-2",
                message="Test issue"
            )
        ]
        
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix='.sarif.json', 
            delete=False
        ) as f:
            output_path = f.name
        
        try:
            returned_path = self.exporter.export_to_file(results, output_path)
            
            self.assertEqual(returned_path, output_path)
            self.assertTrue(os.path.exists(output_path))
            
            # Verify content
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            self.assertEqual(data["version"], "2.1.0")
            self.assertEqual(len(data["runs"][0]["results"]), 1)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)
    
    def test_run_name_included(self):
        """Test that run name is included in invocation."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test",
                result="FAIL",
                severity="SEV-1",
                message="Test"
            )
        ]
        
        report = self.exporter.export(results, run_name="security-scan")
        data = report.to_dict()
        
        self.assertIn("invocations", data["runs"][0])
        self.assertEqual(
            data["runs"][0]["invocations"][0]["commandLine"],
            "security-scan"
        )
    
    def test_additional_properties(self):
        """Test additional properties in results."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test",
                result="FAIL",
                severity="SEV-1",
                message="Test"
            )
        ]
        
        additional = {"repository": "test/repo", "branch": "main"}
        report = self.exporter.export(results, additional_properties=additional)
        
        result = report.runs[0].results[0]
        self.assertEqual(result.details["repository"], "test/repo")
        self.assertEqual(result.details["branch"], "main")


class TestExportSarifConvenience(unittest.TestCase):
    """Tests for convenience functions."""
    
    def test_export_sarif_function(self):
        """Test export_sarif convenience function."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test",
                result="FAIL",
                severity="SEV-1",
                message="Test issue"
            )
        ]
        
        report = export_sarif(results)
        
        self.assertIsInstance(report, SARIFReport)
        self.assertEqual(len(report.runs[0].results), 1)
    
    def test_export_sarif_to_file(self):
        """Test export_sarif with file output."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Test",
                result="FAIL",
                severity="SEV-2",
                message="Test"
            )
        ]
        
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix='.sarif.json', 
            delete=False
        ) as f:
            output_path = f.name
        
        try:
            report = export_sarif(results, output_path=output_path)
            
            self.assertTrue(os.path.exists(output_path))
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            self.assertEqual(data["version"], "2.1.0")
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)


class TestGapConversion(unittest.TestCase):
    """Tests for Gap object conversion."""
    
    def test_from_gap_method(self):
        """Test creating GateResult from Gap object."""
        # Create a mock Gap object
        class MockGap:
            id = "GAP-ABC123"
            reason = "Missing documentation"
            severity = type('Severity', (), {'value': 'SEV-3'})()
            source_file = "src/module.py"
            source_line_start = 10
            source_line_end = 20
            context = "API documentation missing"
            suggested_action = "Add docstrings"
            tags = ["documentation", "api"]
            verified = False
        
        gap = MockGap()
        result = GateResult.from_gap(gap)
        
        self.assertEqual(result.gate_id, "GAP-ABC123")
        self.assertIn("Missing documentation", result.gate_name)
        self.assertEqual(result.severity, "SEV-3")
        self.assertEqual(result.source_file, "src/module.py")
        self.assertEqual(result.line_start, 10)
    
    def test_gaps_to_sarif_function(self):
        """Test gaps_to_sarif convenience function."""
        class MockGap:
            id = "GAP-001"
            reason = "Test gap"
            severity = type('Severity', (), {'value': 'SEV-1'})()
            source_file = None
            source_line_start = None
            source_line_end = None
            context = ""
            suggested_action = ""
            tags = []
            verified = False
        
        report = gaps_to_sarif([MockGap()])
        
        self.assertIsInstance(report, SARIFReport)
        self.assertEqual(len(report.runs[0].results), 1)


class TestSARIFGitHubCompatibility(unittest.TestCase):
    """Tests for GitHub Code Scanning compatibility."""
    
    def test_github_required_fields(self):
        """Test that required fields for GitHub are present."""
        results = [
            GateResult(
                gate_id="GATE-001",
                gate_name="Security Check",
                result="FAIL",
                severity="SEV-1",
                message="Vulnerability found",
                source_file="src/app.py",
                line_start=100
            )
        ]
        
        exporter = SARIFExporter(version="4.0.0")
        report = exporter.export(results)
        json_output = exporter.to_json(report)
        data = json.loads(json_output)
        
        # GitHub Code Scanning requirements
        # 1. Schema URL
        self.assertIn("$schema", data)
        
        # 2. Version 2.1.0
        self.assertEqual(data["version"], "2.1.0")
        
        # 3. Tool information
        run = data["runs"][0]
        self.assertIn("name", run["tool"]["driver"])
        self.assertIn("version", run["tool"]["driver"])
        
        # 4. Result with ruleId and message
        result = run["results"][0]
        self.assertIn("ruleId", result)
        self.assertIn("message", result)
        self.assertIn("text", result["message"])
        
        # 5. Location with URI
        self.assertIn("locations", result)
        location = result["locations"][0]
        self.assertIn("physicalLocation", location)
        self.assertIn("artifactLocation", location["physicalLocation"])
        self.assertIn("uri", location["physicalLocation"]["artifactLocation"])
    
    def test_error_level_for_security_issues(self):
        """Test that SEV-1/SEV-2 appear as errors in GitHub."""
        results = [
            GateResult(
                gate_id="SEC-001",
                gate_name="Critical Security",
                result="FAIL",
                severity="SEV-1",
                message="Critical vulnerability"
            )
        ]
        
        report = export_sarif(results)
        
        # Should be "error" level for GitHub Code Scanning
        self.assertEqual(report.runs[0].results[0].level, SARIFLevel.ERROR)
    
    def test_warning_level_for_medium_issues(self):
        """Test that SEV-3 appears as warnings in GitHub."""
        results = [
            GateResult(
                gate_id="QUAL-001",
                gate_name="Code Quality",
                result="FAIL",
                severity="SEV-3",
                message="Code smell detected"
            )
        ]
        
        report = export_sarif(results)
        
        self.assertEqual(report.runs[0].results[0].level, SARIFLevel.WARNING)


if __name__ == "__main__":
    unittest.main()
