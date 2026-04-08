"""
Graph Exporter for TITAN SAE Inspector.

ITEM-SAE-009: Graph Export Module

Provides functionality to export context graphs to multiple visualization formats:
- DOT (Graphviz)
- Mermaid diagrams
- JSON
- Interactive HTML

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
import json
import html

from src.context.context_graph import (
    ContextGraph,
    ContextNode,
    ContextEdge,
    NodeType,
    EdgeRelation,
    TrustTier,
)
from src.utils.timezone import now_utc_iso


@dataclass
class ExportOptions:
    """Options for graph export."""
    include_trust: bool = True
    include_metadata: bool = True
    include_edges: bool = True
    max_nodes: int = 1000
    max_edges: int = 5000
    color_by_tier: bool = True
    show_labels: bool = True
    interactive: bool = False


class GraphExporter:
    """
    Export Context Graph to various visualization formats.
    
    Supports:
    - DOT (Graphviz): For static graph visualization
    - Mermaid: For markdown/docs embedding
    - JSON: For programmatic access
    - HTML: Interactive web visualization
    
    Usage:
        exporter = GraphExporter(context_graph)
        
        # Export to DOT
        dot_content = exporter.export_dot(include_trust=True)
        
        # Export to Mermaid
        mermaid_content = exporter.export_mermaid()
        
        # Export to JSON
        json_content = exporter.export_json()
        
        # Export to interactive HTML
        html_content = exporter.export_html(interactive=True)
    """
    
    # Color scheme for trust tiers
    TIER_COLORS = {
        TrustTier.TIER_1_TRUSTED: "#28a745",    # Green
        TrustTier.TIER_2_RELIABLE: "#ffc107",   # Yellow
        TrustTier.TIER_3_UNCERTAIN: "#fd7e14",  # Orange
        TrustTier.TIER_4_UNTRUSTED: "#dc3545",  # Red
    }
    
    # Colors for node types
    TYPE_COLORS = {
        NodeType.FILE: "#e3f2fd",      # Light blue
        NodeType.SYMBOL: "#f3e5f5",    # Light purple
        NodeType.MODULE: "#e8f5e9",    # Light green
        NodeType.CONFIG: "#fff8e1",    # Light yellow
        NodeType.CHECKPOINT: "#fce4ec", # Light pink
        NodeType.ARTIFACT: "#f5f5f5",  # Light gray
    }
    
    # Edge styles
    EDGE_STYLES = {
        EdgeRelation.IMPORTS: "solid",
        EdgeRelation.CALLS: "dashed",
        EdgeRelation.DEPENDS_ON: "dotted",
        EdgeRelation.EXTENDS: "bold",
        EdgeRelation.IMPLEMENTS: "dashed",
        EdgeRelation.REFERENCES: "solid",
        EdgeRelation.CONTAINS: "bold",
        EdgeRelation.PRODUCES: "dashed",
    }
    
    def __init__(self, graph: ContextGraph, options: Optional[ExportOptions] = None):
        """
        Initialize GraphExporter.
        
        Args:
            graph: ContextGraph to export
            options: Optional export options
        """
        self._graph = graph
        self._options = options or ExportOptions()
    
    # =========================================================================
    # DOT Export (Graphviz)
    # =========================================================================
    
    def export_dot(
        self,
        include_trust: bool = True,
        include_metadata: bool = True,
        title: str = "Context Graph"
    ) -> str:
        """
        Export graph to DOT format for Graphviz.
        
        Args:
            include_trust: Include trust scores in node labels
            include_metadata: Include metadata as tooltips
            title: Graph title
            
        Returns:
            DOT format string
        """
        lines = [
            f'digraph "{title}" {{',
            '  // Graph settings',
            '  rankdir=LR;',
            '  splines=ortho;',
            '  nodesep=0.5;',
            '  ranksep=1.0;',
            '  node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10];',
            '  edge [fontname="Arial", fontsize=9];',
            '',
            '  // Title',
            f'  label="{title}\\nGenerated: {now_utc_iso()}";',
            '  labelloc="t";',
            '  fontsize=14;',
            '',
        ]
        
        # Nodes
        lines.append("  // Nodes")
        nodes = self._graph.get_all_nodes()[:self._options.max_nodes]
        
        for node in nodes:
            node_id = self._sanitize_id(node.id)
            label = self._sanitize_label(node.id)
            
            if include_trust:
                label = f"{label}\\ntrust={node.trust_score:.2f}"
            
            # Color by tier
            fillcolor = self.TIER_COLORS.get(node.trust_tier, "#ffffff")
            
            # Tooltip
            tooltip = ""
            if include_metadata and node.metadata:
                meta_str = ", ".join(f"{k}={v}" for k, v in list(node.metadata.items())[:3])
                tooltip = f', tooltip="{meta_str}"'
            
            lines.append(
                f'  "{node_id}" [label="{label}", fillcolor="{fillcolor}"{tooltip}];'
            )
        
        lines.append("")
        
        # Edges
        if self._options.include_edges:
            lines.append("  // Edges")
            edges = self._graph._edges[:self._options.max_edges]
            
            for edge in edges:
                from_id = self._sanitize_id(edge.from_id)
                to_id = self._sanitize_id(edge.to_id)
                style = self.EDGE_STYLES.get(edge.relation, "solid")
                
                lines.append(
                    f'  "{from_id}" -> "{to_id}" [label="{edge.relation.value}", style={style}];'
                )
        
        lines.append("}")
        
        return "\n".join(lines)
    
    # =========================================================================
    # Mermaid Export
    # =========================================================================
    
    def export_mermaid(
        self,
        include_trust: bool = True,
        direction: str = "LR"
    ) -> str:
        """
        Export graph to Mermaid diagram format.
        
        Args:
            include_trust: Include trust scores in node labels
            direction: Layout direction (LR, TB, RL, BT)
            
        Returns:
            Mermaid diagram string
        """
        lines = [
            f"```mermaid",
            f"graph {direction}",
        ]
        
        # Subgraphs by tier
        tier_subgraphs = {
            TrustTier.TIER_1_TRUSTED: [],
            TrustTier.TIER_2_RELIABLE: [],
            TrustTier.TIER_3_UNCERTAIN: [],
            TrustTier.TIER_4_UNTRUSTED: [],
        }
        
        nodes = self._graph.get_all_nodes()[:self._options.max_nodes]
        
        for node in nodes:
            node_id = self._sanitize_id(node.id).replace("-", "_")
            label = node.id.split("/")[-1]  # Use filename
            
            if include_trust:
                label = f"{label}<br/>trust={node.trust_score:.2f}"
            
            tier_subgraphs[node.trust_tier].append((node_id, label, node))
        
        # Generate subgraphs
        tier_names = {
            TrustTier.TIER_1_TRUSTED: "Trusted 🟢",
            TrustTier.TIER_2_RELIABLE: "Reliable 🟡",
            TrustTier.TIER_3_UNCERTAIN: "Uncertain 🟠",
            TrustTier.TIER_4_UNTRUSTED: "Untrusted 🔴",
        }
        
        for tier, nodes_list in tier_subgraphs.items():
            if nodes_list:
                lines.append(f"  subgraph {tier.value}")
                for node_id, label, _ in nodes_list:
                    lines.append(f'    {node_id}["{label}"]')
                lines.append("  end")
        
        lines.append("")
        
        # Edges
        if self._options.include_edges:
            edges = self._graph._edges[:self._options.max_edges]
            
            for edge in edges:
                from_id = self._sanitize_id(edge.from_id).replace("-", "_")
                to_id = self._sanitize_id(edge.to_id).replace("-", "_")
                relation = edge.relation.value
                
                lines.append(f'  {from_id} -->|"{relation}"| {to_id}')
        
        lines.append("```")
        
        return "\n".join(lines)
    
    # =========================================================================
    # JSON Export
    # =========================================================================
    
    def export_json(self, pretty: bool = True) -> str:
        """
        Export graph to JSON format.
        
        Args:
            pretty: Pretty-print JSON
            
        Returns:
            JSON string
        """
        data = self._graph.to_dict()
        
        # Add export metadata
        data["export"] = {
            "format": "json",
            "generated_at": now_utc_iso(),
            "node_count": len(data["nodes"]),
            "edge_count": len(data["edges"]),
        }
        
        indent = 2 if pretty else None
        return json.dumps(data, indent=indent, default=str)
    
    # =========================================================================
    # HTML Export
    # =========================================================================
    
    def export_html(
        self,
        interactive: bool = True,
        include_trust: bool = True,
        title: str = "TITAN Context Graph"
    ) -> str:
        """
        Export graph to interactive HTML.
        
        Args:
            interactive: Include interactive JavaScript visualization
            include_trust: Include trust scores
            title: Page title
            
        Returns:
            HTML string
        """
        nodes = self._graph.get_all_nodes()[:self._options.max_nodes]
        edges = self._graph._edges[:self._options.max_edges]
        
        # Prepare nodes data for JavaScript
        nodes_json = []
        for node in nodes:
            nodes_json.append({
                "id": node.id,
                "label": node.id.split("/")[-1],
                "type": node.type.value,
                "trust": round(node.trust_score, 3),
                "tier": node.trust_tier.value,
                "color": self.TIER_COLORS.get(node.trust_tier, "#ffffff"),
            })
        
        # Prepare edges data for JavaScript
        edges_json = []
        for edge in edges:
            edges_json.append({
                "from": edge.from_id,
                "to": edge.to_id,
                "relation": edge.relation.value,
            })
        
        html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
        }}
        
        .header {{
            background: #16213e;
            padding: 20px;
            border-bottom: 1px solid #0f3460;
        }}
        
        .header h1 {{
            font-size: 24px;
            color: #e94560;
        }}
        
        .header p {{
            color: #888;
            margin-top: 5px;
        }}
        
        .stats {{
            display: flex;
            gap: 20px;
            margin-top: 15px;
        }}
        
        .stat {{
            background: #0f3460;
            padding: 10px 15px;
            border-radius: 8px;
        }}
        
        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #e94560;
        }}
        
        .stat-label {{
            font-size: 12px;
            color: #888;
        }}
        
        .legend {{
            display: flex;
            gap: 15px;
            padding: 15px 20px;
            background: #16213e;
            border-bottom: 1px solid #0f3460;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 12px;
        }}
        
        .legend-color {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }}
        
        #graph {{
            width: 100%;
            height: calc(100vh - 180px);
            background: #1a1a2e;
        }}
        
        .node {{
            cursor: pointer;
        }}
        
        .node:hover {{
            filter: brightness(1.2);
        }}
        
        .tooltip {{
            position: absolute;
            background: #16213e;
            border: 1px solid #e94560;
            padding: 10px;
            border-radius: 8px;
            font-size: 12px;
            pointer-events: none;
            z-index: 1000;
            max-width: 300px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🗺️ {html.escape(title)}</h1>
        <p>Generated: {now_utc_iso()}</p>
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{len(nodes)}</div>
                <div class="stat-label">Nodes</div>
            </div>
            <div class="stat">
                <div class="stat-value">{len(edges)}</div>
                <div class="stat-label">Edges</div>
            </div>
            <div class="stat">
                <div class="stat-value">{sum(n.trust_score for n in nodes) / len(nodes):.2f if nodes else 0}</div>
                <div class="stat-label">Avg Trust</div>
            </div>
        </div>
    </div>
    
    <div class="legend">
        <div class="legend-item">
            <div class="legend-color" style="background: #28a745"></div>
            <span>TIER_1 Trusted (≥0.8)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #ffc107"></div>
            <span>TIER_2 Reliable (≥0.6)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #fd7e14"></div>
            <span>TIER_3 Uncertain (≥0.4)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #dc3545"></div>
            <span>TIER_4 Untrusted (<0.4)</span>
        </div>
    </div>
    
    <div id="graph"></div>
    
    <script>
        // Graph data
        const nodes = {json.dumps(nodes_json)};
        const edges = {json.dumps(edges_json)};
        
        // Simple force-directed layout simulation
        const canvas = document.getElementById('graph');
        const ctx = canvas.getContext('2d');
        
        function resize() {{
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight - 180;
        }}
        
        resize();
        window.addEventListener('resize', resize);
        
        // Initialize node positions
        nodes.forEach((node, i) => {{
            node.x = Math.random() * canvas.width;
            node.y = Math.random() * canvas.height;
            node.vx = 0;
            node.vy = 0;
        }});
        
        // Force simulation
        function simulate() {{
            // Repulsion between nodes
            for (let i = 0; i < nodes.length; i++) {{
                for (let j = i + 1; j < nodes.length; j++) {{
                    const dx = nodes[j].x - nodes[i].x;
                    const dy = nodes[j].y - nodes[i].y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = 5000 / (dist * dist);
                    
                    nodes[i].vx -= dx / dist * force;
                    nodes[i].vy -= dy / dist * force;
                    nodes[j].vx += dx / dist * force;
                    nodes[j].vy += dy / dist * force;
                }}
            }}
            
            // Attraction along edges
            edges.forEach(edge => {{
                const source = nodes.find(n => n.id === edge.from);
                const target = nodes.find(n => n.id === edge.to);
                
                if (source && target) {{
                    const dx = target.x - source.x;
                    const dy = target.y - source.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    const force = (dist - 100) * 0.01;
                    
                    source.vx += dx / dist * force;
                    source.vy += dy / dist * force;
                    target.vx -= dx / dist * force;
                    target.vy -= dy / dist * force;
                }}
            }});
            
            // Center gravity
            nodes.forEach(node => {{
                node.vx += (canvas.width / 2 - node.x) * 0.001;
                node.vy += (canvas.height / 2 - node.y) * 0.001;
            }});
            
            // Apply velocity with damping
            nodes.forEach(node => {{
                node.x += node.vx * 0.1;
                node.y += node.vy * 0.1;
                node.vx *= 0.9;
                node.vy *= 0.9;
                
                // Keep in bounds
                node.x = Math.max(50, Math.min(canvas.width - 50, node.x));
                node.y = Math.max(50, Math.min(canvas.height - 50, node.y));
            }});
        }}
        
        function draw() {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            // Draw edges
            ctx.strokeStyle = '#444';
            ctx.lineWidth = 1;
            edges.forEach(edge => {{
                const source = nodes.find(n => n.id === edge.from);
                const target = nodes.find(n => n.id === edge.to);
                
                if (source && target) {{
                    ctx.beginPath();
                    ctx.moveTo(source.x, source.y);
                    ctx.lineTo(target.x, target.y);
                    ctx.stroke();
                }}
            }});
            
            // Draw nodes
            nodes.forEach(node => {{
                // Node circle
                ctx.beginPath();
                ctx.arc(node.x, node.y, 20, 0, Math.PI * 2);
                ctx.fillStyle = node.color;
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 2;
                ctx.stroke();
                
                // Trust score
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 10px Arial';
                ctx.textAlign = 'center';
                ctx.fillText(node.trust.toFixed(1), node.x, node.y + 4);
                
                // Label
                ctx.fillStyle = '#aaa';
                ctx.font = '9px Arial';
                ctx.fillText(node.label.substring(0, 15), node.x, node.y + 35);
            }});
        }}
        
        function animate() {{
            simulate();
            draw();
            requestAnimationFrame(animate);
        }}
        
        animate();
    </script>
</body>
</html>'''
        
        return html_template
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _sanitize_id(self, id_str: str) -> str:
        """Sanitize ID for DOT format."""
        # Replace problematic characters
        return id_str.replace('"', '\\"').replace('\n', ' ')
    
    def _sanitize_label(self, label: str) -> str:
        """Sanitize label for DOT format."""
        # Escape special characters
        return label.replace('"', '\\"').replace('\n', '\\n')
    
    def export_cytoscape(self) -> str:
        """
        Export graph in Cytoscape.js format.
        
        Returns:
            JSON string in Cytoscape.js format
        """
        nodes = self._graph.get_all_nodes()[:self._options.max_nodes]
        edges = self._graph._edges[:self._options.max_edges]
        
        elements = {
            "nodes": [
                {
                    "data": {
                        "id": node.id,
                        "label": node.id.split("/")[-1],
                        "trust": node.trust_score,
                        "tier": node.trust_tier.value,
                        "type": node.type.value,
                    }
                }
                for node in nodes
            ],
            "edges": [
                {
                    "data": {
                        "id": f"{edge.from_id}-{edge.to_id}",
                        "source": edge.from_id,
                        "target": edge.to_id,
                        "label": edge.relation.value,
                    }
                }
                for edge in edges
            ]
        }
        
        return json.dumps(elements, indent=2)


# =============================================================================
# Convenience Functions
# =============================================================================

def export_graph(
    graph: ContextGraph,
    format: str,
    output_path: Optional[str] = None,
    **kwargs
) -> str:
    """
    Export graph to specified format.
    
    Args:
        graph: ContextGraph to export
        format: Export format (dot, mermaid, json, html, cytoscape)
        output_path: Optional path to write output
        **kwargs: Additional export options
        
    Returns:
        Exported content string
    """
    exporter = GraphExporter(graph)
    
    format_handlers = {
        "dot": exporter.export_dot,
        "mermaid": exporter.export_mermaid,
        "json": exporter.export_json,
        "html": exporter.export_html,
        "cytoscape": exporter.export_cytoscape,
    }
    
    handler = format_handlers.get(format)
    if not handler:
        raise ValueError(f"Unknown format: {format}. Supported: {list(format_handlers.keys())}")
    
    content = handler(**kwargs)
    
    if output_path:
        Path(output_path).write_text(content)
    
    return content
