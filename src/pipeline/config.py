from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class PipelineConfig:
    """Configuration for ContentPipeline execution."""
    max_validation_passes: int = 2  # PAT-24
    checkpoint_dir: str = ".ai/checkpoints"
    enable_gap_emission: bool = True
    seed: Optional[int] = None
    budget_tokens: int = 50000
    timeout_per_phase_ms: int = 30000
    hygiene_strip_patterns: List[str] = field(default_factory=lambda: [
        r"# DEBUG:.*",
        r"<!-- META:.*-->",
        r"# TODO:.*",
    ])
    artifact_output_dir: str = "outputs"
    nav_map_path: str = ".ai/nav_map.json"
    prompt_registry_path: str = "config/prompt_registry.yaml"
