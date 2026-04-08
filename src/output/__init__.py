"""
TITAN Protocol Output Module.

ITEM-PROD-01: SARIF Output Format for GitHub Code Scanning integration.

Provides exporters for various output formats including SARIF 2.1.0
for GitHub Code Scanning integration.
"""

from .sarif_exporter import (
    # Core classes
    SARIFExporter,
    SARIFReport,
    SARIFRun,
    SARIFResult,
    SARIFRule,
    SARIFLocation,
    SARIFLevel,
    
    # Data class for gate results
    GateResult,
    
    # Utility functions
    map_severity_to_sarif,
    export_sarif,
    gaps_to_sarif,
)


__all__ = [
    # Core classes
    'SARIFExporter',
    'SARIFReport',
    'SARIFRun',
    'SARIFResult',
    'SARIFRule',
    'SARIFLocation',
    'SARIFLevel',
    
    # Data class
    'GateResult',
    
    # Utility functions
    'map_severity_to_sarif',
    'export_sarif',
    'gaps_to_sarif',
]
