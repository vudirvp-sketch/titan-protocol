"""
TITAN FUSE Protocol - Mode Selector

Implements mode selection logic for v3.2.1.
Determines execution mode based on CLI args, config files, and defaults.
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from enum import Enum
import yaml


class ExecutionMode(Enum):
    """Available execution modes."""
    DIRECT = "direct"
    AUTO = "auto"
    MANUAL = "manual"
    PRESET = "preset"
    HYBRID = "hybrid"


@dataclass
class ModeSelection:
    """Result of mode selection."""
    mode: ExecutionMode
    preset_name: Optional[str] = None
    config_source: str = "default"
    features_enabled: Dict = None
    validation_errors: List[str] = None
    
    def __post_init__(self):
        if self.features_enabled is None:
            self.features_enabled = {}
        if self.validation_errors is None:
            self.validation_errors = []


class ModeSelector:
    """
    Mode selection logic for TITAN FUSE Protocol.
    
    Selection priority:
    1. CLI argument (--mode=auto, --mode=preset:NAME, etc.)
    2. MODE-CONFIG.yaml mode field
    3. Default (DIRECT)
    """
    
    # CLI argument patterns
    CLI_PATTERNS = {
        "--mode=": "direct_parse",
        "-m ": "direct_parse_space",
    }
    
    # Required features by mode
    MODE_REQUIREMENTS = {
        ExecutionMode.AUTO: ["intent_classifier"],
        ExecutionMode.PRESET: ["preset_file"],
        ExecutionMode.HYBRID: ["state_serialization", "intent_classifier"],
        ExecutionMode.MANUAL: [],  # No special requirements
        ExecutionMode.DIRECT: [],  # No special requirements
    }
    
    def __init__(self, repo_root: Path = None):
        """Initialize mode selector with repository root."""
        self.repo_root = repo_root or Path.cwd()
        self.mode_config_path = self.repo_root / "MODE-CONFIG.yaml"
        self.presets_dir = self.repo_root / "presets"
        
        # Load MODE-CONFIG.yaml if exists
        self.mode_config = self._load_mode_config()
    
    def _load_mode_config(self) -> Dict:
        """Load MODE-CONFIG.yaml."""
        if self.mode_config_path.exists():
            try:
                with open(self.mode_config_path) as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
        return {}
    
    def select_mode(self, cli_args: List[str] = None) -> ModeSelection:
        """
        Select execution mode based on available inputs.
        
        Args:
            cli_args: Command line arguments (defaults to sys.argv)
            
        Returns:
            ModeSelection with selected mode and configuration
        """
        cli_args = cli_args or sys.argv
        errors = []
        
        # Step 1: Check CLI arguments
        cli_mode, cli_preset, cli_source = self._parse_cli_args(cli_args)
        if cli_mode:
            selection = ModeSelection(
                mode=cli_mode,
                preset_name=cli_preset,
                config_source=cli_source
            )
            # Validate and return
            validation = self._validate_mode(selection)
            if validation:
                selection.validation_errors = validation
                # Fallback to DIRECT on validation failure
                selection.mode = ExecutionMode.DIRECT
                selection.config_source = "fallback"
            return selection
        
        # Step 2: Check MODE-CONFIG.yaml
        config_mode, config_preset = self._parse_config()
        if config_mode:
            selection = ModeSelection(
                mode=config_mode,
                preset_name=config_preset,
                config_source="MODE-CONFIG.yaml"
            )
            validation = self._validate_mode(selection)
            if validation:
                selection.validation_errors = validation
                # Try fallback mode
                fallback = self.mode_config.get("fallback", {}).get("mode", "direct")
                selection.mode = ExecutionMode(fallback)
                selection.config_source = "fallback"
            return selection
        
        # Step 3: Default to DIRECT
        return ModeSelection(
            mode=ExecutionMode.DIRECT,
            config_source="default"
        )
    
    def _parse_cli_args(self, args: List[str]) -> Tuple[Optional[ExecutionMode], Optional[str], str]:
        """
        Parse CLI arguments for mode selection.
        
        Returns:
            Tuple of (mode, preset_name, source)
        """
        for arg in args:
            # Handle --mode=auto, --mode=preset:NAME, etc.
            if arg.startswith("--mode="):
                mode_str = arg.split("=", 1)[1]
                return self._parse_mode_string(mode_str, "cli_arg")
            
            # Handle -m auto, -m preset:NAME, etc.
            if arg == "-m" or arg == "--mode":
                idx = args.index(arg)
                if idx + 1 < len(args):
                    return self._parse_mode_string(args[idx + 1], "cli_arg")
        
        return None, None, ""
    
    def _parse_mode_string(self, mode_str: str, source: str) -> Tuple[ExecutionMode, Optional[str], str]:
        """Parse a mode string like 'auto' or 'preset:code_review'."""
        # Check for preset mode
        if mode_str.startswith("preset:"):
            preset_name = mode_str.split(":", 1)[1]
            return ExecutionMode.PRESET, preset_name, source
        
        # Check for valid mode
        try:
            mode = ExecutionMode(mode_str.lower())
            return mode, None, source
        except ValueError:
            # Invalid mode, will be handled by validation
            return ExecutionMode.DIRECT, None, source
    
    def _parse_config(self) -> Tuple[Optional[ExecutionMode], Optional[str]]:
        """Parse MODE-CONFIG.yaml for mode selection."""
        mode_str = self.mode_config.get("mode", "")
        if not mode_str:
            return None, None
        
        # Handle preset:NAME format
        if mode_str.startswith("preset:"):
            preset_name = mode_str.split(":", 1)[1]
            return ExecutionMode.PRESET, preset_name
        
        try:
            return ExecutionMode(mode_str.lower()), None
        except ValueError:
            return None, None
    
    def _validate_mode(self, selection: ModeSelection) -> List[str]:
        """
        Validate mode selection.
        
        Returns list of validation errors (empty if valid).
        """
        errors = []
        requirements = self.MODE_REQUIREMENTS.get(selection.mode, [])
        
        for req in requirements:
            if req == "intent_classifier":
                # Check if intent classifier is available
                try:
                    from src.classification import IntentClassifierV1
                except ImportError:
                    errors.append("intent_classifier module not available")
            
            elif req == "preset_file":
                # Check if preset file exists
                if not selection.preset_name:
                    errors.append("preset name not specified")
                else:
                    preset_path = self.presets_dir / selection.preset_name / "workflow.yaml"
                    if not preset_path.exists():
                        errors.append(f"preset '{selection.preset_name}' not found")
            
            elif req == "state_serialization":
                # Check if state serialization is enabled
                if not self.mode_config.get("hybrid", {}).get("state_preservation"):
                    errors.append("state_serialization not configured for HYBRID mode")
        
        # Check HYBRID mode availability
        if selection.mode == ExecutionMode.HYBRID:
            if not self.mode_config.get("hybrid", {}).get("enabled", False):
                errors.append("HYBRID mode is not enabled (Phase 3 feature)")
        
        return errors
    
    def get_mode_config(self, mode: ExecutionMode) -> Dict:
        """Get configuration for a specific mode."""
        mode_configs = {
            ExecutionMode.DIRECT: self.mode_config.get("direct", {}),
            ExecutionMode.AUTO: self.mode_config.get("auto", {}),
            ExecutionMode.MANUAL: self.mode_config.get("manual", {}),
            ExecutionMode.PRESET: self.mode_config.get("preset", {}),
            ExecutionMode.HYBRID: self.mode_config.get("hybrid", {}),
        }
        return mode_configs.get(mode, {})
    
    def get_enabled_features(self, mode: ExecutionMode) -> Dict:
        """Get enabled features for a mode."""
        mode_config = self.get_mode_config(mode)
        return mode_config.get("features", {})


def select_mode(repo_root: Path = None, cli_args: List[str] = None) -> ModeSelection:
    """
    Convenience function to select mode.
    
    Args:
        repo_root: Repository root path
        cli_args: Command line arguments
        
    Returns:
        ModeSelection result
    """
    selector = ModeSelector(repo_root)
    return selector.select_mode(cli_args)
