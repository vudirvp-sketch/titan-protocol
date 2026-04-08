"""
SAE Inspector - Context Graph Visualization and Debugging Tool.

ITEM-SAE-009: SAE Inspector CLI Implementation

Provides CLI interface for inspecting and visualizing the Self-Awareness Engine
components including context graph, trust scores, drift status, and summarization.

Key Features:
- Context graph inspection and visualization
- Trust score display with tier classification
- Drift detection reporting
- Stale node identification
- Session summary and pruning status
- Multiple output formats (table, JSON, ASCII, graph exports)

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import json
import logging
import sys

from src.context.context_graph import (
    ContextGraph,
    ContextNode,
    ContextEdge,
    NodeType,
    EdgeRelation,
    TrustTier,
    VersionVector,
)
from src.context.trust_engine import TrustEngine, TrustEngineConfig
from src.context.drift_detector import DriftDetector, DriftLevel, DriftReport
from src.context.summarization import RecursiveSummarizer, ExecutionStage, StageSummary
from src.utils.timezone import now_utc, now_utc_iso


class OutputFormat(Enum):
    """Output format for inspector results."""
    TABLE = "table"
    JSON = "json"
    ASCII = "ascii"
    SUMMARY = "summary"


@dataclass
class InspectionResult:
    """Result of an inspection operation."""
    command: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    timestamp: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "command": self.command,
            "success": self.success,
            "data": self.data,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class SAEInspector:
    """
    SAE Inspector - CLI tool for Context Graph visualization and debugging.
    
    Provides commands for inspecting various SAE components:
    - inspect: Show current context graph
    - trust: Display trust scores for all nodes
    - drift: Show drift status for all nodes
    - stale: List stale context nodes
    - summary: Show session summary with pruning status
    - graph: Generate graph visualization
    
    Usage:
        inspector = SAEInspector(context_graph, trust_engine, drift_detector)
        
        # Inspect context graph
        result = inspector.inspect(format=OutputFormat.TABLE)
        print(result.message)
        
        # Show trust scores
        result = inspector.trust(threshold=0.5)
        
        # Check drift
        result = inspector.drift(level=DriftLevel.MODERATE)
        
        # Find stale nodes
        result = inspector.stale(fix=False)
        
        # Show session summary
        result = inspector.summary(stages=5)
        
        # Export graph
        result = inspector.graph(output="context_graph.dot")
    """
    
    def __init__(
        self,
        context_graph: Optional[ContextGraph] = None,
        trust_engine: Optional[TrustEngine] = None,
        drift_detector: Optional[DriftDetector] = None,
        summarizer: Optional[RecursiveSummarizer] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the SAE Inspector.
        
        Args:
            context_graph: Context graph to inspect
            trust_engine: Trust engine for score management
            drift_detector: Drift detector for stale detection
            summarizer: Recursive summarizer for session info
            config: Optional configuration
        """
        self._graph = context_graph
        self._trust_engine = trust_engine
        self._drift_detector = drift_detector
        self._summarizer = summarizer
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Initialize components if not provided but graph is available
        if self._graph:
            if not self._trust_engine:
                self._trust_engine = TrustEngine(context_graph=self._graph)
            if not self._drift_detector:
                self._drift_detector = DriftDetector(context_graph=self._graph)
        if not self._summarizer:
            self._summarizer = RecursiveSummarizer()
    
    # =========================================================================
    # Configuration
    # =========================================================================
    
    def set_context_graph(self, graph: ContextGraph) -> None:
        """Set the context graph to inspect."""
        self._graph = graph
        if self._trust_engine:
            self._trust_engine.set_context_graph(graph)
        if self._drift_detector:
            self._drift_detector.set_context_graph(graph)
    
    def load_context(self, path: str) -> InspectionResult:
        """
        Load context graph from file.
        
        Args:
            path: Path to context_graph.json file
            
        Returns:
            InspectionResult with load status
        """
        try:
            self._graph = ContextGraph.load(path)
            if self._trust_engine:
                self._trust_engine.set_context_graph(self._graph)
            if self._drift_detector:
                self._drift_detector.set_context_graph(self._graph)
            
            stats = self._graph.get_stats()
            return InspectionResult(
                command="load",
                success=True,
                data={"path": path, "stats": stats},
                message=f"Loaded context graph from {path}: {stats['total_nodes']} nodes, {stats['total_edges']} edges"
            )
        except Exception as e:
            return InspectionResult(
                command="load",
                success=False,
                message=f"Failed to load context graph: {e}"
            )
    
    # =========================================================================
    # Inspect Commands
    # =========================================================================
    
    def inspect(
        self,
        format: OutputFormat = OutputFormat.TABLE,
        node_type: Optional[NodeType] = None,
        limit: int = 50
    ) -> InspectionResult:
        """
        Show current context graph.
        
        Args:
            format: Output format (table, json, ascii, summary)
            node_type: Filter by node type
            limit: Maximum nodes to display
            
        Returns:
            InspectionResult with graph data
        """
        if not self._graph:
            return InspectionResult(
                command="inspect",
                success=False,
                message="No context graph loaded. Use load() first."
            )
        
        nodes = self._graph.get_all_nodes()
        
        # Filter by type
        if node_type:
            nodes = [n for n in nodes if n.type == node_type]
        
        # Apply limit
        total_nodes = len(nodes)
        nodes = nodes[:limit]
        
        if format == OutputFormat.JSON:
            return InspectionResult(
                command="inspect",
                success=True,
                data={
                    "nodes": [n.to_dict() for n in nodes],
                    "edges": [e.to_dict() for e in self._graph._edges[:limit]],
                    "stats": self._graph.get_stats(),
                },
                message=json.dumps({
                    "nodes": [n.to_dict() for n in nodes],
                    "total_nodes": total_nodes,
                    "showing": len(nodes),
                }, indent=2)
            )
        
        elif format == OutputFormat.ASCII:
            ascii_graph = self.render_graph_ascii(nodes)
            return InspectionResult(
                command="inspect",
                success=True,
                data={"total_nodes": total_nodes, "showing": len(nodes)},
                message=ascii_graph
            )
        
        elif format == OutputFormat.SUMMARY:
            stats = self._graph.get_stats()
            summary = self._render_inspect_summary(stats)
            return InspectionResult(
                command="inspect",
                success=True,
                data=stats,
                message=summary
            )
        
        else:  # TABLE format
            table = self._render_nodes_table(nodes)
            return InspectionResult(
                command="inspect",
                success=True,
                data={
                    "total_nodes": total_nodes,
                    "showing": len(nodes),
                    "nodes": [n.to_dict() for n in nodes],
                },
                message=table
            )
    
    def trust(
        self,
        threshold: Optional[float] = None,
        tier: Optional[TrustTier] = None,
        format: OutputFormat = OutputFormat.TABLE
    ) -> InspectionResult:
        """
        Display trust scores for all nodes.
        
        Args:
            threshold: Minimum trust score threshold
            tier: Filter by trust tier
            format: Output format
            
        Returns:
            InspectionResult with trust data
        """
        if not self._graph:
            return InspectionResult(
                command="trust",
                success=False,
                message="No context graph loaded."
            )
        
        nodes = self._graph.get_all_nodes()
        
        # Filter by threshold
        if threshold is not None:
            nodes = [n for n in nodes if n.trust_score >= threshold]
        
        # Filter by tier
        if tier is not None:
            nodes = [n for n in nodes if n.trust_tier == tier]
        
        # Sort by trust score descending
        nodes = sorted(nodes, key=lambda n: n.trust_score, reverse=True)
        
        if format == OutputFormat.JSON:
            return InspectionResult(
                command="trust",
                success=True,
                data={
                    "nodes": [n.to_dict() for n in nodes],
                    "engine_stats": self._trust_engine.get_stats_summary() if self._trust_engine else {},
                },
                message=json.dumps([{"id": n.id, "trust": n.trust_score, "tier": n.trust_tier.value} for n in nodes], indent=2)
            )
        
        # Table format
        table = self._render_trust_table(nodes, threshold)
        
        return InspectionResult(
            command="trust",
            success=True,
            data={
                "total_nodes": len(nodes),
                "nodes": [n.to_dict() for n in nodes],
                "threshold": threshold,
            },
            message=table
        )
    
    def drift(
        self,
        level: Optional[DriftLevel] = None,
        format: OutputFormat = OutputFormat.TABLE
    ) -> InspectionResult:
        """
        Show drift status for all nodes.
        
        Args:
            level: Filter by drift level
            format: Output format
            
        Returns:
            InspectionResult with drift data
        """
        if not self._graph or not self._drift_detector:
            return InspectionResult(
                command="drift",
                success=False,
                message="No context graph or drift detector available."
            )
        
        # Get full drift report
        report = self._drift_detector.detect_all_drift()
        
        # Filter by level
        drifted_nodes = report.drifted_nodes
        if level is not None:
            drifted_nodes = [d for d in drifted_nodes if d.drift_level == level]
        
        if format == OutputFormat.JSON:
            return InspectionResult(
                command="drift",
                success=True,
                data={"report": report.to_dict()},
                message=json.dumps(report.to_dict(), indent=2)
            )
        
        # Table format
        table = self._render_drift_report(report, drifted_nodes)
        
        return InspectionResult(
            command="drift",
            success=True,
            data={
                "report": report.to_dict(),
                "filtered_count": len(drifted_nodes),
            },
            message=table
        )
    
    def stale(
        self,
        fix: bool = False,
        max_age_hours: float = 24.0,
        min_trust: float = 0.3
    ) -> InspectionResult:
        """
        List stale context nodes.
        
        Args:
            fix: If True, attempt to refresh stale nodes
            max_age_hours: Maximum age before considering stale
            min_trust: Minimum trust score to not be considered stale
            
        Returns:
            InspectionResult with stale node data
        """
        if not self._graph:
            return InspectionResult(
                command="stale",
                success=False,
                message="No context graph loaded."
            )
        
        stale_nodes = self._graph.detect_stale_nodes(
            max_age_hours=max_age_hours,
            min_trust=min_trust
        )
        
        fixed_count = 0
        if fix and stale_nodes:
            # Attempt to refresh by removing and re-adding
            for node in stale_nodes:
                if self._graph.remove_node(node.id):
                    fixed_count += 1
        
        table = self._render_stale_table(stale_nodes, max_age_hours, min_trust)
        
        message = table
        if fix:
            message += f"\n\n🔧 Fixed: Removed {fixed_count} stale nodes"
        
        return InspectionResult(
            command="stale",
            success=True,
            data={
                "stale_count": len(stale_nodes),
                "fixed_count": fixed_count,
                "max_age_hours": max_age_hours,
                "min_trust": min_trust,
                "nodes": [n.to_dict() for n in stale_nodes],
            },
            message=message
        )
    
    def summary(self, stages: int = 5) -> InspectionResult:
        """
        Show session summary with pruning status.
        
        Args:
            stages: Number of recent stages to show
            
        Returns:
            InspectionResult with session summary
        """
        data = {
            "graph_stats": self._graph.get_stats() if self._graph else {},
            "trust_stats": self._trust_engine.get_stats_summary() if self._trust_engine else {},
            "summarizer_stats": self._summarizer.get_stats() if self._summarizer else {},
        }
        
        message = self._render_session_summary(data, stages)
        
        return InspectionResult(
            command="summary",
            success=True,
            data=data,
            message=message
        )
    
    def graph(
        self,
        output: str,
        format: str = "dot",
        include_trust: bool = True
    ) -> InspectionResult:
        """
        Generate graph visualization.
        
        Args:
            output: Output file path
            format: Output format (dot, mermaid, json, html)
            include_trust: Include trust scores in visualization
            
        Returns:
            InspectionResult with export status
        """
        if not self._graph:
            return InspectionResult(
                command="graph",
                success=False,
                message="No context graph loaded."
            )
        
        try:
            from src.tools.graph_export import GraphExporter
            
            exporter = GraphExporter(self._graph)
            
            if format == "dot":
                content = exporter.export_dot(include_trust=include_trust)
            elif format == "mermaid":
                content = exporter.export_mermaid(include_trust=include_trust)
            elif format == "json":
                content = exporter.export_json()
            elif format == "html":
                content = exporter.export_html(interactive=True, include_trust=include_trust)
            else:
                return InspectionResult(
                    command="graph",
                    success=False,
                    message=f"Unknown format: {format}. Supported: dot, mermaid, json, html"
                )
            
            # Write to file
            Path(output).write_text(content)
            
            return InspectionResult(
                command="graph",
                success=True,
                data={
                    "output": output,
                    "format": format,
                    "size_bytes": len(content),
                },
                message=f"Graph exported to {output} ({format} format, {len(content)} bytes)"
            )
            
        except ImportError:
            # Fallback to basic export
            content = self._basic_graph_export(format, include_trust)
            Path(output).write_text(content)
            
            return InspectionResult(
                command="graph",
                success=True,
                data={"output": output, "format": format, "size_bytes": len(content)},
                message=f"Graph exported to {output} (basic {format} format)"
            )
    
    # =========================================================================
    # Rendering Methods
    # =========================================================================
    
    def _render_nodes_table(self, nodes: List[ContextNode]) -> str:
        """Render nodes as a table."""
        if not nodes:
            return "No nodes in context graph."
        
        lines = [
            "\n📊 Context Graph Nodes",
            "=" * 100,
            f"{'ID':<40} {'Type':<12} {'Trust':<8} {'Tier':<20} {'Location':<30}",
            "-" * 100,
        ]
        
        for node in nodes:
            trust_str = f"{node.trust_score:.2f}"
            tier_str = node.trust_tier.value
            location = node.location[:28] + ".." if len(node.location) > 30 else node.location
            node_id = node.id[:38] + ".." if len(node.id) > 40 else node.id
            
            lines.append(f"{node_id:<40} {node.type.value:<12} {trust_str:<8} {tier_str:<20} {location:<30}")
        
        lines.append("-" * 100)
        lines.append(f"Total: {len(nodes)} nodes")
        
        return "\n".join(lines)
    
    def _render_trust_table(
        self,
        nodes: List[ContextNode],
        threshold: Optional[float]
    ) -> str:
        """Render trust scores as a table."""
        if not nodes:
            return "No nodes match the criteria."
        
        lines = [
            "\n🎯 Trust Score Report",
            "=" * 80,
            f"{'Node ID':<40} {'Trust':<10} {'Tier':<20} {'Usage':<10}",
            "-" * 80,
        ]
        
        tier_colors = {
            TrustTier.TIER_1_TRUSTED: "🟢",
            TrustTier.TIER_2_RELIABLE: "🟡",
            TrustTier.TIER_3_UNCERTAIN: "🟠",
            TrustTier.TIER_4_UNTRUSTED: "🔴",
        }
        
        for node in nodes:
            icon = tier_colors.get(node.trust_tier, "⚪")
            node_id = node.id[:38] + ".." if len(node.id) > 40 else node.id
            trust_str = f"{node.trust_score:.3f}"
            tier_str = f"{icon} {node.trust_tier.value}"
            
            lines.append(f"{node_id:<40} {trust_str:<10} {tier_str:<20} {node.usage_count:<10}")
        
        lines.append("-" * 80)
        
        if threshold is not None:
            lines.append(f"Filtered by trust >= {threshold:.2f}")
        lines.append(f"Total: {len(nodes)} nodes")
        
        # Add tier distribution
        tier_counts = {}
        for node in nodes:
            tier_counts[node.trust_tier.value] = tier_counts.get(node.trust_tier.value, 0) + 1
        
        lines.append("\n📈 Tier Distribution:")
        for tier in TrustTier:
            count = tier_counts.get(tier.value, 0)
            bar = "█" * (count // 2) if count > 0 else ""
            lines.append(f"  {tier.value:<20} {count:>4} {bar}")
        
        return "\n".join(lines)
    
    def _render_drift_report(
        self,
        report: DriftReport,
        drifted_nodes: List[Any]
    ) -> str:
        """Render drift report."""
        lines = [
            "\n🌊 Drift Detection Report",
            "=" * 80,
            f"Total Nodes Checked: {report.total_nodes}",
            f"Drifted Nodes: {len(report.drifted_nodes)}",
            f"Severe Drift: {report.severe_drift_count}",
            f"Average Drift Score: {report.average_drift_score:.3f}",
            f"Has Severe Drift: {'⚠️ YES' if report.has_severe_drift else '✅ NO'}",
            "",
        ]
        
        if report.recommendations:
            lines.append("📋 Recommendations:")
            for rec in report.recommendations:
                lines.append(f"  • {rec}")
            lines.append("")
        
        if drifted_nodes:
            lines.append("-" * 80)
            lines.append(f"{'Node ID':<40} {'Score':<10} {'Level':<15} {'Action':<20}")
            lines.append("-" * 80)
            
            for result in drifted_nodes:
                node_id = result.node_id[:38] + ".." if len(result.node_id) > 40 else result.node_id
                score = f"{result.drift_score:.3f}"
                level_icons = {
                    DriftLevel.NONE: "✅",
                    DriftLevel.MINOR: "📝",
                    DriftLevel.MODERATE: "⚠️",
                    DriftLevel.SEVERE: "🚨",
                }
                icon = level_icons.get(result.drift_level, "❓")
                level = f"{icon} {result.drift_level.value}"
                
                lines.append(f"{node_id:<40} {score:<10} {level:<15} {result.recommended_action:<20}")
        
        return "\n".join(lines)
    
    def _render_stale_table(
        self,
        stale_nodes: List[ContextNode],
        max_age_hours: float,
        min_trust: float
    ) -> str:
        """Render stale nodes table."""
        lines = [
            "\n🧹 Stale Context Nodes",
            "=" * 80,
            f"Max Age: {max_age_hours}h | Min Trust: {min_trust}",
            f"Found: {len(stale_nodes)} stale nodes",
            "",
        ]
        
        if not stale_nodes:
            lines.append("✅ No stale nodes detected!")
            return "\n".join(lines)
        
        lines.append(f"{'Node ID':<40} {'Trust':<10} {'Last Modified':<25}")
        lines.append("-" * 80)
        
        for node in stale_nodes:
            node_id = node.id[:38] + ".." if len(node.id) > 40 else node.id
            trust = f"{node.trust_score:.2f}"
            last_mod = node.last_modified.isoformat() if node.last_modified else "Never"
            
            lines.append(f"{node_id:<40} {trust:<10} {last_mod:<25}")
        
        lines.append("-" * 80)
        lines.append(f"Total: {len(stale_nodes)} stale nodes")
        
        return "\n".join(lines)
    
    def _render_session_summary(self, data: Dict[str, Any], stages: int) -> str:
        """Render session summary."""
        lines = [
            "\n📋 SAE Session Summary",
            "=" * 60,
        ]
        
        # Graph stats
        graph_stats = data.get("graph_stats", {})
        if graph_stats:
            lines.extend([
                "\n📊 Context Graph:",
                f"  • Nodes: {graph_stats.get('total_nodes', 0)}",
                f"  • Edges: {graph_stats.get('total_edges', 0)}",
                f"  • Avg Trust: {graph_stats.get('avg_trust_score', 0):.3f}",
                f"  • Low Trust Nodes: {graph_stats.get('low_trust_nodes_count', 0)}",
                f"  • Stale Nodes: {graph_stats.get('stale_nodes_count', 0)}",
            ])
        
        # Trust stats
        trust_stats = data.get("trust_stats", {})
        if trust_stats:
            lines.extend([
                "\n🎯 Trust Engine:",
                f"  • Total Updates: {trust_stats.get('total_updates', 0)}",
                f"  • Boosts: {trust_stats.get('total_boosts', 0)}",
                f"  • Penalties: {trust_stats.get('total_penalties', 0)}",
                f"  • Decays: {trust_stats.get('total_decays', 0)}",
            ])
        
        # Summarizer stats
        summarizer_stats = data.get("summarizer_stats", {})
        if summarizer_stats:
            lines.extend([
                "\n📝 Summarizer:",
                f"  • Stages Summarized: {summarizer_stats.get('stages_summarized', 0)}",
                f"  • Stages Pruned: {summarizer_stats.get('stages_pruned', 0)}",
                f"  • Max Retained: {summarizer_stats.get('max_stages_retained', 3)}",
                f"  • Bytes Saved: {summarizer_stats.get('bytes_saved', 0)}",
            ])
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)
    
    def _render_inspect_summary(self, stats: Dict[str, Any]) -> str:
        """Render inspect summary."""
        return f"""
📊 Context Graph Summary
========================
Total Nodes:    {stats.get('total_nodes', 0)}
Total Edges:    {stats.get('total_edges', 0)}
Avg Trust:      {stats.get('avg_trust_score', 0):.3f}
Min Trust:      {stats.get('min_trust_score', 0):.3f}
Max Trust:      {stats.get('max_trust_score', 0):.3f}
Stale Nodes:    {stats.get('stale_nodes_count', 0)}
Low Trust:      {stats.get('low_trust_nodes_count', 0)}
"""
    
    def render_graph_ascii(self, nodes: List[ContextNode]) -> str:
        """
        Render graph as ASCII art.
        
        Args:
            nodes: Nodes to render
            
        Returns:
            ASCII representation of graph
        """
        lines = [
            "\n🗺️  Context Graph (ASCII)",
            "=" * 60,
        ]
        
        if not nodes:
            lines.append("(empty graph)")
            return "\n".join(lines)
        
        # Simple tree representation
        for node in nodes[:20]:  # Limit to 20 for readability
            icon = {"file": "📄", "symbol": "🔷", "module": "📦", "config": "⚙️"}.get(node.type.value, "❓")
            trust_icon = "🟢" if node.trust_score >= 0.7 else "🟡" if node.trust_score >= 0.4 else "🔴"
            lines.append(f"  {icon} {trust_icon} {node.id}")
            
            # Show edges
            if self._graph:
                edges = self._graph.get_edges_from(node.id)[:3]
                for edge in edges:
                    lines.append(f"    └──[{edge.relation.value}]──> {edge.to_id[:30]}")
        
        if len(nodes) > 20:
            lines.append(f"  ... and {len(nodes) - 20} more nodes")
        
        return "\n".join(lines)
    
    def _basic_graph_export(self, format: str, include_trust: bool) -> str:
        """Basic graph export without GraphExporter."""
        if format == "json":
            return self._graph.to_json()
        
        # DOT format fallback
        lines = [
            "digraph ContextGraph {",
            "  rankdir=LR;",
            "  node [shape=box];",
            "",
        ]
        
        for node in self._graph.get_all_nodes():
            color = {"TIER_1_TRUSTED": "green", "TIER_2_RELIABLE": "yellow", 
                    "TIER_3_UNCERTAIN": "orange", "TIER_4_UNTRUSTED": "red"}.get(
                node.trust_tier.value, "gray"
            )
            label = node.id.replace('"', '\\"')
            if include_trust:
                label = f"{label}\\ntrust={node.trust_score:.2f}"
            lines.append(f'  "{node.id}" [label="{label}", style=filled, fillcolor={color}];')
        
        lines.append("")
        
        for edge in self._graph._edges:
            lines.append(f'  "{edge.from_id}" -> "{edge.to_id}" [label="{edge.relation.value}"];')
        
        lines.append("}")
        
        return "\n".join(lines)


# =============================================================================
# Module-level convenience
# =============================================================================

def create_inspector(
    context_graph_path: Optional[str] = None,
    **kwargs
) -> SAEInspector:
    """
    Create an SAE Inspector instance.
    
    Args:
        context_graph_path: Optional path to load context graph from
        **kwargs: Additional arguments for SAEInspector
        
    Returns:
        Configured SAEInspector instance
    """
    inspector = SAEInspector(**kwargs)
    
    if context_graph_path:
        inspector.load_context(context_graph_path)
    
    return inspector
