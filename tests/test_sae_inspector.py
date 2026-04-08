"""
Tests for SAE Inspector - ITEM-SAE-009.

Tests the SAE Inspector CLI tool functionality:
- Context graph inspection
- Trust score display
- Drift detection reporting
- Stale node identification
- Session summary
- Graph export
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.tools.sae_inspector import (
    SAEInspector,
    InspectionResult,
    OutputFormat,
    create_inspector,
)
from src.tools.graph_export import (
    GraphExporter,
    ExportOptions,
    export_graph,
)
from src.context.context_graph import (
    ContextGraph,
    ContextNode,
    ContextEdge,
    NodeType,
    EdgeRelation,
    TrustTier,
)
from src.context.trust_engine import TrustEngine, TrustEngineConfig
from src.context.drift_detector import DriftDetector, DriftLevel


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_context_graph():
    """Create a sample context graph for testing."""
    graph = ContextGraph(session_id="test-session")
    
    # Add nodes with different trust levels
    nodes = [
        ContextNode(
            id="src/main.py",
            type=NodeType.FILE,
            location="src/main.py",
            trust_score=0.9,
            usage_count=10,
        ),
        ContextNode(
            id="src/utils.py",
            type=NodeType.FILE,
            location="src/utils.py",
            trust_score=0.7,
            usage_count=5,
        ),
        ContextNode(
            id="src/config.yaml",
            type=NodeType.CONFIG,
            location="src/config.yaml",
            trust_score=0.3,
            usage_count=1,
        ),
        ContextNode(
            id="test_main",
            type=NodeType.SYMBOL,
            location="src/main.py::test_main",
            trust_score=0.85,
            usage_count=8,
        ),
    ]
    
    for node in nodes:
        graph.add_node(node)
    
    # Add edges
    edges = [
        ContextEdge("src/main.py", "src/utils.py", EdgeRelation.IMPORTS),
        ContextEdge("src/main.py", "test_main", EdgeRelation.CONTAINS),
    ]
    
    for edge in edges:
        graph.add_edge(edge)
    
    return graph


@pytest.fixture
def sample_stale_nodes_graph():
    """Create a graph with stale nodes."""
    graph = ContextGraph()
    
    # Recent node
    graph.add_node(ContextNode(
        id="recent.py",
        type=NodeType.FILE,
        location="recent.py",
        trust_score=0.9,
        last_modified=datetime.utcnow(),
    ))
    
    # Old node (stale by age)
    old_time = datetime.utcnow() - timedelta(hours=48)
    graph.add_node(ContextNode(
        id="old.py",
        type=NodeType.FILE,
        location="old.py",
        trust_score=0.6,
        last_modified=old_time,
    ))
    
    # Low trust node (stale by trust)
    graph.add_node(ContextNode(
        id="low_trust.py",
        type=NodeType.FILE,
        location="low_trust.py",
        trust_score=0.2,
    ))
    
    return graph


@pytest.fixture
def inspector(sample_context_graph):
    """Create an SAE Inspector with sample graph."""
    trust_engine = TrustEngine(context_graph=sample_context_graph)
    drift_detector = DriftDetector(context_graph=sample_context_graph)
    
    return SAEInspector(
        context_graph=sample_context_graph,
        trust_engine=trust_engine,
        drift_detector=drift_detector,
    )


# =============================================================================
# SAEInspector Tests
# =============================================================================

class TestSAEInspector:
    """Tests for SAEInspector class."""
    
    def test_inspector_initialization(self, sample_context_graph):
        """Test inspector initialization."""
        inspector = SAEInspector(context_graph=sample_context_graph)
        
        assert inspector._graph == sample_context_graph
        assert inspector._trust_engine is not None
        assert inspector._drift_detector is not None
    
    def test_inspect_table_format(self, inspector):
        """Test inspect command with table format."""
        result = inspector.inspect(format=OutputFormat.TABLE)
        
        assert result.success
        assert result.command == "inspect"
        assert "Context Graph Nodes" in result.message
        assert "Total:" in result.message
    
    def test_inspect_json_format(self, inspector):
        """Test inspect command with JSON format."""
        result = inspector.inspect(format=OutputFormat.JSON)
        
        assert result.success
        assert "nodes" in result.data
        assert len(result.data["nodes"]) == 4
    
    def test_inspect_summary_format(self, inspector):
        """Test inspect command with summary format."""
        result = inspector.inspect(format=OutputFormat.SUMMARY)
        
        assert result.success
        assert "Context Graph Summary" in result.message
        assert "Total Nodes:" in result.message
    
    def test_inspect_filter_by_type(self, inspector):
        """Test inspect with node type filter."""
        result = inspector.inspect(node_type=NodeType.CONFIG)
        
        assert result.success
        # Should only show config nodes
        assert len(result.data["nodes"]) == 1
        assert result.data["nodes"][0]["type"] == "config"
    
    def test_inspect_limit(self, inspector):
        """Test inspect with limit."""
        result = inspector.inspect(limit=2)
        
        assert result.success
        assert len(result.data["nodes"]) == 2
        assert result.data["total_nodes"] == 4
    
    def test_trust_command_no_filter(self, inspector):
        """Test trust command without filters."""
        result = inspector.trust()
        
        assert result.success
        assert result.command == "trust"
        assert "Trust Score Report" in result.message
        assert len(result.data["nodes"]) == 4
    
    def test_trust_command_with_threshold(self, inspector):
        """Test trust command with threshold filter."""
        result = inspector.trust(threshold=0.8)
        
        assert result.success
        # Only nodes with trust >= 0.8
        for node in result.data["nodes"]:
            assert node["trust_score"] >= 0.8
    
    def test_trust_command_with_tier(self, inspector):
        """Test trust command with tier filter."""
        result = inspector.trust(tier=TrustTier.TIER_1_TRUSTED)
        
        assert result.success
        for node in result.data["nodes"]:
            assert node["trust_tier"] == "TIER_1_TRUSTED"
    
    def test_drift_command(self, inspector):
        """Test drift command."""
        result = inspector.drift()
        
        assert result.success
        assert result.command == "drift"
        assert "Drift Detection Report" in result.message
    
    def test_drift_command_with_level_filter(self, inspector):
        """Test drift command with level filter."""
        result = inspector.drift(level=DriftLevel.SEVERE)
        
        assert result.success
        # Should have filtered results
        assert "filtered_count" in result.data
    
    def test_stale_command(self, inspector):
        """Test stale command."""
        result = inspector.stale()
        
        assert result.success
        assert result.command == "stale"
        assert "Stale Context Nodes" in result.message
    
    def test_stale_command_with_fix(self, sample_stale_nodes_graph):
        """Test stale command with fix option."""
        inspector = SAEInspector(context_graph=sample_stale_nodes_graph)
        result = inspector.stale(fix=True, min_trust=0.4)
        
        assert result.success
        assert result.data["fixed_count"] > 0
    
    def test_summary_command(self, inspector):
        """Test summary command."""
        result = inspector.summary()
        
        assert result.success
        assert result.command == "summary"
        assert "SAE Session Summary" in result.message
        assert "graph_stats" in result.data
    
    def test_no_graph_error(self):
        """Test error when no graph is loaded."""
        inspector = SAEInspector()
        result = inspector.inspect()
        
        assert not result.success
        assert "No context graph loaded" in result.message
    
    def test_load_context(self, inspector, tmp_path):
        """Test loading context from file."""
        # Save graph
        graph_path = tmp_path / "context_graph.json"
        inspector._graph.save(str(graph_path))
        
        # Create new inspector and load
        new_inspector = SAEInspector()
        result = new_inspector.load_context(str(graph_path))
        
        assert result.success
        assert new_inspector._graph is not None
        assert new_inspector._graph.get_stats()["total_nodes"] == 4
    
    def test_render_graph_ascii(self, inspector):
        """Test ASCII graph rendering."""
        nodes = inspector._graph.get_all_nodes()
        ascii_graph = inspector.render_graph_ascii(nodes)
        
        assert "Context Graph (ASCII)" in ascii_graph
        assert "src/main.py" in ascii_graph


# =============================================================================
# GraphExporter Tests
# =============================================================================

class TestGraphExporter:
    """Tests for GraphExporter class."""
    
    def test_export_dot(self, sample_context_graph):
        """Test DOT export."""
        exporter = GraphExporter(sample_context_graph)
        dot_content = exporter.export_dot()
        
        assert "digraph" in dot_content
        assert "rankdir=LR" in dot_content
        assert "src/main.py" in dot_content
    
    def test_export_dot_with_trust(self, sample_context_graph):
        """Test DOT export with trust scores."""
        exporter = GraphExporter(sample_context_graph)
        dot_content = exporter.export_dot(include_trust=True)
        
        assert "trust=" in dot_content
    
    def test_export_mermaid(self, sample_context_graph):
        """Test Mermaid export."""
        exporter = GraphExporter(sample_context_graph)
        mermaid_content = exporter.export_mermaid()
        
        assert "```mermaid" in mermaid_content
        assert "graph LR" in mermaid_content
    
    def test_export_json(self, sample_context_graph):
        """Test JSON export."""
        exporter = GraphExporter(sample_context_graph)
        json_content = exporter.export_json()
        
        data = json.loads(json_content)
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 4
    
    def test_export_html(self, sample_context_graph):
        """Test HTML export."""
        exporter = GraphExporter(sample_context_graph)
        html_content = exporter.export_html()
        
        assert "<!DOCTYPE html>" in html_content
        assert "TITAN Context Graph" in html_content
        assert "<script>" in html_content
    
    def test_export_cytoscape(self, sample_context_graph):
        """Test Cytoscape.js export."""
        exporter = GraphExporter(sample_context_graph)
        cyto_content = exporter.export_cytoscape()
        
        data = json.loads(cyto_content)
        assert "nodes" in data
        assert "edges" in data
    
    def test_export_options(self, sample_context_graph):
        """Test export with custom options."""
        options = ExportOptions(
            max_nodes=2,
            max_edges=1,
            include_trust=False,
        )
        exporter = GraphExporter(sample_context_graph, options=options)
        
        json_content = exporter.export_json()
        data = json.loads(json_content)
        
        assert len(data["nodes"]) <= 2


# =============================================================================
# InspectionResult Tests
# =============================================================================

class TestInspectionResult:
    """Tests for InspectionResult dataclass."""
    
    def test_to_dict(self):
        """Test result serialization."""
        result = InspectionResult(
            command="test",
            success=True,
            data={"key": "value"},
            message="Test message",
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["command"] == "test"
        assert result_dict["success"] is True
        assert result_dict["data"]["key"] == "value"
        assert result_dict["message"] == "Test message"
    
    def test_default_timestamp(self):
        """Test timestamp is auto-generated."""
        result = InspectionResult(command="test", success=True)
        
        assert result.timestamp is not None
        assert "T" in result.timestamp  # ISO format


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""
    
    def test_create_inspector(self):
        """Test create_inspector factory."""
        inspector = create_inspector()
        
        assert inspector is not None
        assert isinstance(inspector, SAEInspector)
    
    def test_create_inspector_with_path(self, tmp_path, sample_context_graph):
        """Test create_inspector with context path."""
        graph_path = tmp_path / "context_graph.json"
        sample_context_graph.save(str(graph_path))
        
        inspector = create_inspector(context_graph_path=str(graph_path))
        
        assert inspector._graph is not None
        assert inspector._graph.get_stats()["total_nodes"] == 4
    
    def test_export_graph_convenience(self, sample_context_graph):
        """Test export_graph convenience function."""
        json_content = export_graph(sample_context_graph, "json")
        
        data = json.loads(json_content)
        assert "nodes" in data
    
    def test_export_graph_to_file(self, sample_context_graph, tmp_path):
        """Test export_graph to file."""
        output_path = tmp_path / "graph.dot"
        
        content = export_graph(
            sample_context_graph,
            "dot",
            output_path=str(output_path)
        )
        
        assert output_path.exists()
        assert "digraph" in output_path.read_text()
    
    def test_export_graph_invalid_format(self, sample_context_graph):
        """Test export_graph with invalid format."""
        with pytest.raises(ValueError) as exc_info:
            export_graph(sample_context_graph, "invalid_format")
        
        assert "Unknown format" in str(exc_info.value)


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for SAE Inspector."""
    
    def test_full_inspection_workflow(self, sample_context_graph):
        """Test complete inspection workflow."""
        # Create inspector
        inspector = SAEInspector(context_graph=sample_context_graph)
        
        # Run all commands
        inspect_result = inspector.inspect(format=OutputFormat.SUMMARY)
        trust_result = inspector.trust()
        drift_result = inspector.drift()
        stale_result = inspector.stale()
        summary_result = inspector.summary()
        
        # All should succeed
        assert inspect_result.success
        assert trust_result.success
        assert drift_result.success
        assert stale_result.success
        assert summary_result.success
    
    def test_graph_export_all_formats(self, sample_context_graph, tmp_path):
        """Test exporting graph in all formats."""
        exporter = GraphExporter(sample_context_graph)
        
        formats = ["dot", "mermaid", "json", "html"]
        
        for fmt in formats:
            output_path = tmp_path / f"graph.{fmt}"
            content = export_graph(sample_context_graph, fmt, str(output_path))
            
            assert output_path.exists()
            assert len(content) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
