"""
Tests for Dependency Graph Schema (ITEM-BOOT-001).

Tests the DEPENDENCY_GRAPH_SCHEMA functionality:
- Graph node and edge creation
- Import extraction (Python and JavaScript)
- Cycle detection
- Topological ordering
- Serialization/deserialization

Author: TITAN FUSE Team
Version: 5.0.0
"""

import pytest
import sys
import os
import json
import tempfile
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from navigation.nav_map_builder import (
    DependencyGraphBuilder,
    DependencyGraph,
    DependencyNode,
    DependencyEdge,
    DependencyCycle,
    NodeType,
    RelationType,
    create_dependency_graph_builder
)


class TestNodeType:
    """Tests for NodeType enum."""
    
    def test_node_type_values(self):
        """Test that all required node types exist."""
        assert NodeType.FILE.value == "file"
        assert NodeType.SYMBOL.value == "symbol"
        assert NodeType.MODULE.value == "module"
        assert NodeType.CLASS.value == "class"
        assert NodeType.FUNCTION.value == "function"
        assert NodeType.VARIABLE.value == "variable"


class TestRelationType:
    """Tests for RelationType enum."""
    
    def test_relation_type_values(self):
        """Test that all required relation types exist."""
        assert RelationType.IMPORTS.value == "imports"
        assert RelationType.CALLS.value == "calls"
        assert RelationType.DEPENDS_ON.value == "depends_on"
        assert RelationType.EXTENDS.value == "extends"
        assert RelationType.IMPLEMENTS.value == "implements"
        assert RelationType.REFERENCES.value == "references"
        assert RelationType.CONTAINS.value == "contains"


class TestDependencyNode:
    """Tests for DependencyNode dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        node = DependencyNode(
            id="file:test.py",
            type=NodeType.FILE,
            name="test.py",
            location="test.py"
        )
        
        assert node.id == "file:test.py"
        assert node.type == NodeType.FILE
        assert node.name == "test.py"
        assert node.location == "test.py"
        assert node.metadata == {}
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        node = DependencyNode(
            id="class:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            location="test.py:10",
            metadata={"external": False}
        )
        
        d = node.to_dict()
        
        assert d["id"] == "class:MyClass"
        assert d["type"] == "class"
        assert d["name"] == "MyClass"
        assert d["location"] == "test.py:10"
        assert d["metadata"]["external"] is False
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "id": "module:os",
            "type": "module",
            "name": "os",
            "location": "os",
            "metadata": {"imported_from": "main.py"}
        }
        
        node = DependencyNode.from_dict(data)
        
        assert node.id == "module:os"
        assert node.type == NodeType.MODULE
        assert node.name == "os"
        assert node.location == "os"
        assert node.metadata["imported_from"] == "main.py"


class TestDependencyEdge:
    """Tests for DependencyEdge dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        edge = DependencyEdge(
            from_id="file:main.py",
            to_id="module:os",
            relation=RelationType.IMPORTS
        )
        
        assert edge.from_id == "file:main.py"
        assert edge.to_id == "module:os"
        assert edge.relation == RelationType.IMPORTS
        assert edge.weight == 1.0
        assert edge.metadata == {}
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        edge = DependencyEdge(
            from_id="class:Child",
            to_id="class:Parent",
            relation=RelationType.EXTENDS,
            weight=2.0,
            metadata={"line": 10}
        )
        
        d = edge.to_dict()
        
        assert d["from"] == "class:Child"
        assert d["to"] == "class:Parent"
        assert d["relation"] == "extends"
        assert d["weight"] == 2.0
        assert d["metadata"]["line"] == 10
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "from": "file:app.js",
            "to": "module:react",
            "relation": "imports",
            "weight": 1.5,
            "metadata": {"statement": "import React from 'react'"}
        }
        
        edge = DependencyEdge.from_dict(data)
        
        assert edge.from_id == "file:app.js"
        assert edge.to_id == "module:react"
        assert edge.relation == RelationType.IMPORTS
        assert edge.weight == 1.5


class TestDependencyCycle:
    """Tests for DependencyCycle dataclass."""
    
    def test_init(self):
        """Test initialization."""
        cycle = DependencyCycle(
            cycle_id="CYCLE-1",
            nodes=["A", "B", "C", "A"],
            severity="warning",
            description="Circular dependency: A -> B -> C -> A"
        )
        
        assert cycle.cycle_id == "CYCLE-1"
        assert cycle.nodes == ["A", "B", "C", "A"]
        assert cycle.severity == "warning"
    
    def test_to_dict(self):
        """Test serialization."""
        cycle = DependencyCycle(
            cycle_id="CYCLE-1",
            nodes=["A", "B", "A"],
            severity="error",
            description="Test cycle"
        )
        
        d = cycle.to_dict()
        
        assert d["cycle_id"] == "CYCLE-1"
        assert d["nodes"] == ["A", "B", "A"]
        assert d["severity"] == "error"
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "cycle_id": "CYCLE-2",
            "nodes": ["X", "Y", "Z", "X"],
            "severity": "warning",
            "description": "Test"
        }
        
        cycle = DependencyCycle.from_dict(data)
        
        assert cycle.cycle_id == "CYCLE-2"
        assert cycle.nodes == ["X", "Y", "Z", "X"]


class TestDependencyGraph:
    """Tests for DependencyGraph dataclass."""
    
    def test_init(self):
        """Test initialization."""
        graph = DependencyGraph(
            nodes={},
            edges=[],
            metadata={},
            cycles=[],
            topological_order=[]
        )
        
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0
        assert graph.cycles == []
    
    def test_to_dict(self):
        """Test serialization."""
        node = DependencyNode(
            id="file:test.py",
            type=NodeType.FILE,
            name="test.py",
            location="test.py"
        )
        edge = DependencyEdge(
            from_id="file:test.py",
            to_id="module:os",
            relation=RelationType.IMPORTS
        )
        
        graph = DependencyGraph(
            nodes={"file:test.py": node},
            edges=[edge],
            metadata={"total_nodes": 1},
            cycles=[],
            topological_order=["file:test.py"]
        )
        
        d = graph.to_dict()
        
        assert len(d["nodes"]) == 1
        assert len(d["edges"]) == 1
        assert d["metadata"]["total_nodes"] == 1
        assert d["topological_order"] == ["file:test.py"]
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "nodes": [{
                "id": "file:app.py",
                "type": "file",
                "name": "app.py",
                "location": "app.py",
                "metadata": {}
            }],
            "edges": [{
                "from": "file:app.py",
                "to": "module:sys",
                "relation": "imports",
                "weight": 1.0,
                "metadata": {}
            }],
            "metadata": {"total_nodes": 1, "cycle_detected": False},
            "cycles": [],
            "topological_order": ["file:app.py"]
        }
        
        graph = DependencyGraph.from_dict(data)
        
        assert len(graph.nodes) == 1
        assert len(graph.edges) == 1
        assert graph.metadata["cycle_detected"] is False
    
    def test_to_json(self):
        """Test JSON serialization."""
        graph = DependencyGraph(
            nodes={},
            edges=[],
            metadata={"test": True},
            cycles=[],
            topological_order=[]
        )
        
        json_str = graph.to_json()
        
        assert '"test": true' in json_str
        assert '"nodes"' in json_str
    
    def test_from_json(self):
        """Test JSON deserialization."""
        json_str = '''{
            "nodes": [],
            "edges": [],
            "metadata": {"test": true},
            "cycles": [],
            "topological_order": []
        }'''
        
        graph = DependencyGraph.from_json(json_str)
        
        assert graph.metadata["test"] is True


class TestDependencyGraphBuilder:
    """Tests for DependencyGraphBuilder class."""
    
    def test_init(self):
        """Test builder initialization."""
        builder = DependencyGraphBuilder()
        
        assert builder._config == {}
        assert len(builder._nodes) == 0
        assert len(builder._edges) == 0
    
    def test_build_empty_graph(self):
        """Test building graph with no files."""
        builder = DependencyGraphBuilder()
        
        graph = builder.build_dependency_graph([], {})
        
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0
        assert graph.cycles == []
        assert graph.topological_order == []
    
    def test_build_single_file(self):
        """Test building graph with a single file."""
        builder = DependencyGraphBuilder()
        
        graph = builder.build_dependency_graph(
            files=["main.py"],
            content_map={"main.py": "print('hello')"}
        )
        
        # Should have at least the file node
        assert len(graph.nodes) >= 1
        assert "file:main.py" in graph.nodes
        assert graph.metadata["files_analyzed"] == 1
    
    def test_graph_complete(self):
        """Test that dependency graph has all nodes and edges."""
        builder = DependencyGraphBuilder()
        
        content = """
import os
import sys

def main():
    print("hello")
    
if __name__ == "__main__":
    main()
"""
        
        graph = builder.build_dependency_graph(
            files=["app.py"],
            content_map={"app.py": content}
        )
        
        # Check nodes
        assert len(graph.nodes) >= 1
        
        # Check edges exist
        assert len(graph.edges) >= 2  # At least os and sys imports
        
        # Check metadata
        assert "total_nodes" in graph.metadata
        assert "total_edges" in graph.metadata
        assert "cycle_detected" in graph.metadata


class TestImportExtraction:
    """Tests for import extraction functionality."""
    
    def test_python_import_extraction(self):
        """Test Python import statement extraction."""
        builder = DependencyGraphBuilder()
        
        content = """
import os
import sys
from pathlib import Path
from collections import defaultdict
"""
        
        graph = builder.build_dependency_graph(
            files=["main.py"],
            content_map={"main.py": content}
        )
        
        # Check module nodes were created
        module_nodes = [n for n in graph.nodes.values() if n.type == NodeType.MODULE]
        module_names = [n.name for n in module_nodes]
        
        assert "os" in module_names
        assert "sys" in module_names
        assert "pathlib" in module_names
        assert "collections" in module_names
        
        # Check import edges
        import_edges = [e for e in graph.edges if e.relation == RelationType.IMPORTS]
        assert len(import_edges) >= 4
    
    def test_javascript_import_extraction(self):
        """Test JavaScript import statement extraction."""
        builder = DependencyGraphBuilder()
        
        content = """
import React from 'react';
import { useState } from 'react';
const lodash = require('lodash');
"""
        
        graph = builder.build_dependency_graph(
            files=["app.js"],
            content_map={"app.js": content}
        )
        
        # Check module nodes
        module_nodes = [n for n in graph.nodes.values() if n.type == NodeType.MODULE]
        module_names = [n.name for n in module_nodes]
        
        assert "react" in module_names
        assert "lodash" in module_names
    
    def test_from_import_extraction(self):
        """Test 'from X import Y' extraction."""
        builder = DependencyGraphBuilder()
        
        content = "from typing import Dict, List, Optional"
        
        graph = builder.build_dependency_graph(
            files=["types_test.py"],
            content_map={"types_test.py": content}
        )
        
        module_nodes = [n for n in graph.nodes.values() if n.type == NodeType.MODULE]
        module_names = [n.name for n in module_nodes]
        
        assert "typing" in module_names


class TestCallExtraction:
    """Tests for function call extraction."""
    
    def test_function_call_extraction(self):
        """Test function call extraction."""
        builder = DependencyGraphBuilder()
        
        content = """
def helper():
    pass

def main():
    helper()
    custom_func()
"""
        
        graph = builder.build_dependency_graph(
            files=["calls.py"],
            content_map={"calls.py": content}
        )
        
        # Check call edges exist
        call_edges = [e for e in graph.edges if e.relation == RelationType.CALLS]
        
        # Should have calls to helper and custom_func
        call_targets = [e.to_id for e in call_edges]
        assert any("helper" in t for t in call_targets)


class TestCycleDetection:
    """Tests for cycle detection functionality."""
    
    def test_cycles_detected_when_present(self):
        """Test that cycles are detected if present."""
        builder = DependencyGraphBuilder()
        
        # Create content that would create a circular import scenario
        # Note: This is a simplified test - real cycle detection
        # would require actual circular file imports
        
        # Manually add nodes and edges to create a cycle
        builder._nodes["A"] = DependencyNode(
            id="A", type=NodeType.MODULE, name="A", location="A"
        )
        builder._nodes["B"] = DependencyNode(
            id="B", type=NodeType.MODULE, name="B", location="B"
        )
        builder._nodes["C"] = DependencyNode(
            id="C", type=NodeType.MODULE, name="C", location="C"
        )
        
        # Create cycle: A -> B -> C -> A
        builder._adjacency = {
            "A": {"B"},
            "B": {"C"},
            "C": {"A"}
        }
        
        cycles = builder._detect_cycles()
        
        assert len(cycles) >= 1
        assert cycles[0].severity == "warning"
    
    def test_no_cycles_in_acyclic_graph(self):
        """Test that no cycles are detected in acyclic graph."""
        builder = DependencyGraphBuilder()
        
        content = """
import os
import sys
"""
        
        graph = builder.build_dependency_graph(
            files=["main.py"],
            content_map={"main.py": content}
        )
        
        assert len(graph.cycles) == 0
        assert graph.metadata["cycle_detected"] is False


class TestTopologicalOrder:
    """Tests for topological ordering functionality."""
    
    def test_topo_order_valid(self):
        """Test that topological order is valid."""
        builder = DependencyGraphBuilder()
        
        content = """
import os
import sys
"""
        
        graph = builder.build_dependency_graph(
            files=["main.py"],
            content_map={"main.py": content}
        )
        
        # Check that topological order contains all nodes
        assert len(graph.topological_order) == len(graph.nodes)
        
        # All nodes should be in the order
        for node_id in graph.nodes:
            assert node_id in graph.topological_order
    
    def test_topo_order_dependencies_first(self):
        """Test that dependencies come before dependents in topological order."""
        builder = DependencyGraphBuilder()
        
        # Create nodes manually
        builder._nodes["module:base"] = DependencyNode(
            id="module:base", type=NodeType.MODULE, name="base", location="base"
        )
        builder._nodes["module:derived"] = DependencyNode(
            id="module:derived", type=NodeType.MODULE, name="derived", location="derived"
        )
        
        # derived depends on base
        builder._adjacency["module:derived"] = {"module:base"}
        
        order = builder._topological_sort()
        
        # base should come before derived in topological order
        if "module:base" in order and "module:derived" in order:
            assert order.index("module:base") < order.index("module:derived")


class TestBuildFromDirectory:
    """Tests for building dependency graph from directory."""
    
    def test_build_from_directory(self):
        """Test building graph from directory."""
        builder = DependencyGraphBuilder()
        
        # Create temporary directory with test files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Python file
            py_file = Path(tmpdir) / "test.py"
            py_file.write_text("import os\n")
            
            # Create JavaScript file
            js_file = Path(tmpdir) / "test.js"
            js_file.write_text("import React from 'react';\n")
            
            graph = builder.build_from_directory(tmpdir)
            
            assert len(graph.nodes) >= 2
            assert graph.metadata["files_analyzed"] == 2
    
    def test_build_from_directory_with_exclusions(self):
        """Test that hidden directories and exclusions work."""
        builder = DependencyGraphBuilder()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create regular file
            regular_file = Path(tmpdir) / "regular.py"
            regular_file.write_text("print('hello')")
            
            # Create file in hidden directory
            hidden_dir = Path(tmpdir) / ".hidden"
            hidden_dir.mkdir()
            hidden_file = hidden_dir / "secret.py"
            hidden_file.write_text("secret = True")
            
            # Create file in __pycache__
            cache_dir = Path(tmpdir) / "__pycache__"
            cache_dir.mkdir()
            cache_file = cache_dir / "cached.pyc"
            cache_file.write_text("cached")
            
            graph = builder.build_from_directory(tmpdir, extensions=['.py'])
            
            # Should only have the regular file
            assert graph.metadata["files_analyzed"] == 1


class TestSerialization:
    """Tests for serialization and deserialization."""
    
    def test_roundtrip(self):
        """Test serialization roundtrip."""
        builder = DependencyGraphBuilder()
        
        content = """
import os
import sys

class MyClass:
    pass
"""
        
        graph = builder.build_dependency_graph(
            files=["test.py"],
            content_map={"test.py": content}
        )
        
        # Serialize
        json_str = graph.to_json()
        
        # Deserialize
        restored = DependencyGraph.from_json(json_str)
        
        assert len(restored.nodes) == len(graph.nodes)
        assert len(restored.edges) == len(graph.edges)
        assert restored.metadata["cycle_detected"] == graph.metadata["cycle_detected"]
    
    def test_json_artifact_generation(self):
        """Test that JSON artifact can be generated."""
        builder = DependencyGraphBuilder()
        
        content = """
import os
from typing import Dict

class Handler:
    pass

def process():
    pass
"""
        
        graph = builder.build_dependency_graph(
            files=["handler.py"],
            content_map={"handler.py": content}
        )
        
        # Generate JSON
        json_output = graph.to_json(indent=2)
        
        # Verify it's valid JSON
        parsed = json.loads(json_output)
        
        assert "nodes" in parsed
        assert "edges" in parsed
        assert "metadata" in parsed
        assert "cycles" in parsed
        assert "topological_order" in parsed


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_dependency_graph_builder(self):
        """Test create_dependency_graph_builder factory."""
        builder = create_dependency_graph_builder()
        
        assert isinstance(builder, DependencyGraphBuilder)
    
    def test_create_with_config(self):
        """Test factory with configuration."""
        config = {"test": True}
        builder = create_dependency_graph_builder(config=config)
        
        assert builder._config == config


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_empty_content(self):
        """Test handling of empty file content."""
        builder = DependencyGraphBuilder()
        
        graph = builder.build_dependency_graph(
            files=["empty.py"],
            content_map={"empty.py": ""}
        )
        
        # Should have the file node
        assert "file:empty.py" in graph.nodes
        assert len(graph.cycles) == 0
    
    def test_syntax_error_content(self):
        """Test handling of content with syntax errors."""
        builder = DependencyGraphBuilder()
        
        # Invalid Python - should still create file node
        content = "this is not valid python !!!"
        
        graph = builder.build_dependency_graph(
            files=["invalid.py"],
            content_map={"invalid.py": content}
        )
        
        assert "file:invalid.py" in graph.nodes
    
    def test_nonexistent_file_in_map(self):
        """Test that files listed but not in content map are handled."""
        builder = DependencyGraphBuilder()
        
        # File in list but not in content map
        graph = builder.build_dependency_graph(
            files=["missing.py"],
            content_map={}
        )
        
        # Should still create node for the file
        assert "file:missing.py" in graph.nodes


class TestMetadataCompleteness:
    """Tests for metadata completeness in DEPENDENCY_GRAPH_SCHEMA."""
    
    def test_metadata_has_required_fields(self):
        """Test that metadata has all required fields."""
        builder = DependencyGraphBuilder()
        
        graph = builder.build_dependency_graph(
            files=["test.py"],
            content_map={"test.py": "import os"}
        )
        
        assert "total_nodes" in graph.metadata
        assert "total_edges" in graph.metadata
        assert "files_analyzed" in graph.metadata
        assert "cycle_detected" in graph.metadata
        assert "cycle_count" in graph.metadata
        assert "builder_version" in graph.metadata
        assert "timestamp" in graph.metadata
    
    def test_node_has_required_fields(self):
        """Test that nodes have all required fields."""
        builder = DependencyGraphBuilder()
        
        graph = builder.build_dependency_graph(
            files=["test.py"],
            content_map={"test.py": "import os"}
        )
        
        for node in graph.nodes.values():
            d = node.to_dict()
            assert "id" in d
            assert "type" in d
            assert "name" in d
            assert "location" in d
            assert "metadata" in d
    
    def test_edge_has_required_fields(self):
        """Test that edges have all required fields."""
        builder = DependencyGraphBuilder()
        
        graph = builder.build_dependency_graph(
            files=["test.py"],
            content_map={"test.py": "import os"}
        )
        
        for edge in graph.edges:
            d = edge.to_dict()
            assert "from" in d
            assert "to" in d
            assert "relation" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
