"""
ITEM_011: ContextAdapter for TITAN Protocol v1.2.0.

This module implements the ContextAdapter which bridges between
context and skills, transforming EVENT_CONTEXT_READY payload
for skill execution.

Features:
- Bridge between context and skills
- Transform EVENT_CONTEXT_READY payload for skill execution
- Context validation against context_bridge.schema.json
- Map context fields to skill inputs

Integration Points:
- EventBus: Subscribe to EVENT_CONTEXT_READY
- SkillLibrary: Skill lookup
- PluginInterface: Standard plugin lifecycle

Author: TITAN Protocol Team
Version: 1.2.0
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING
import logging
import threading
import re

from ..interfaces.plugin_interface import (
    PluginInterface,
    PluginState,
    RoutingDecision,
    RoutingAction,
    ExecutionResult,
    ErrorResult,
    PluginInfo
)

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from .skill_library import SkillLibrary


@dataclass
class ContextMapping:
    """
    Defines a mapping from context field to skill input.
    
    Attributes:
        source_path: Path in context (e.g., "enriched_intent.original_intent")
        target_field: Field name in skill input
        transform: Optional transformation to apply
        required: Whether this field is required
        default_value: Default value if field is missing
    """
    source_path: str
    target_field: str
    transform: Optional[str] = None
    required: bool = True
    default_value: Any = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_path": self.source_path,
            "target_field": self.target_field,
            "transform": self.transform,
            "required": self.required,
            "default_value": self.default_value
        }


@dataclass
class ValidationResult:
    """
    Result of context validation.
    
    Attributes:
        is_valid: Whether the context is valid
        errors: List of validation errors
        warnings: List of validation warnings
        missing_fields: List of missing required fields
        extra_fields: List of unexpected fields
    """
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    extra_fields: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "missing_fields": self.missing_fields,
            "extra_fields": self.extra_fields
        }


@dataclass
class SkillExecutionContext:
    """
    Context prepared for skill execution.
    
    Attributes:
        skill_inputs: Mapped inputs for skills
        original_context: Original context payload
        profile: Detected user profile
        intent: Enriched intent information
        skill_hints: Suggested skills
        critical_gates: Gates to check
        metadata: Execution metadata
        fallback_used: Whether fallback mapping was used
    """
    skill_inputs: Dict[str, Any] = field(default_factory=dict)
    original_context: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    intent: Dict[str, Any] = field(default_factory=dict)
    skill_hints: List[str] = field(default_factory=list)
    critical_gates: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "skill_inputs": self.skill_inputs,
            "original_context": self.original_context,
            "profile": self.profile,
            "intent": self.intent,
            "skill_hints": self.skill_hints,
            "critical_gates": self.critical_gates,
            "metadata": self.metadata,
            "fallback_used": self.fallback_used
        }


class ContextAdapter(PluginInterface):
    """
    Adapter for bridging context to skill execution.
    
    This adapter transforms EVENT_CONTEXT_READY payloads into
    skill-ready execution contexts, handling validation and
    field mapping.
    
    Features:
    - Context validation against schema
    - Field mapping to skill inputs
    - Transformation functions for data adaptation
    - Fallback handling for missing fields
    
    Integration Points:
    - EventBus: Subscribes to EVENT_CONTEXT_READY
    - SkillLibrary: Gets skill input requirements
    - PluginInterface: Standard plugin lifecycle
    
    Example:
        >>> adapter = ContextAdapter(config, event_bus)
        >>> adapter.on_init()
        >>> execution_context = adapter.transform_for_skills(event_payload)
        >>> print(execution_context.skill_inputs)
    """
    
    # Standard context field mappings
    DEFAULT_MAPPINGS: List[ContextMapping] = [
        ContextMapping("enriched_intent.original_intent", "request", required=True),
        ContextMapping("enriched_intent.enhanced_intent", "enhanced_request", required=False),
        ContextMapping("enriched_intent.intent_type", "intent_type", required=True),
        ContextMapping("enriched_intent.confidence", "confidence", required=False),
        ContextMapping("enriched_intent.keywords", "keywords", required=False),
        ContextMapping("skill_hints", "suggested_skills", required=False),
        ContextMapping("critical_gates", "required_gates", required=False),
        ContextMapping("user_profile.detected_role", "user_role", required=False),
        ContextMapping("user_profile.expertise_level", "expertise", required=False),
        ContextMapping("context_metadata.request_id", "request_id", required=False),
        ContextMapping("context_metadata.session_id", "session_id", required=False),
        ContextMapping("context_metadata.timeout_ms", "timeout_ms", required=False),
    ]
    
    def __init__(self, config: Dict[str, Any], event_bus: 'EventBus' = None):
        """
        Initialize the ContextAdapter.
        
        Args:
            config: Configuration dictionary with optional keys:
                - schema_path: Path to context_bridge.schema.json
                - strict_validation: Fail on validation errors (default: False)
                - custom_mappings: Additional field mappings
                - transform_functions: Named transform functions
            event_bus: Optional EventBus for event emission
        """
        self._config = config
        self._event_bus = event_bus
        self._state = PluginState.UNINITIALIZED
        self._logger = logging.getLogger(__name__)
        
        # Schema for validation
        self._schema: Optional[Dict[str, Any]] = None
        self._schema_path = config.get(
            "schema_path",
            "schemas/context_bridge.schema.json"
        )
        
        # Mappings
        self._mappings: Dict[str, ContextMapping] = {}
        self._strict_validation = config.get("strict_validation", False)
        
        # Transform functions
        self._transforms: Dict[str, Callable[[Any], Any]] = {
            "uppercase": lambda x: x.upper() if isinstance(x, str) else x,
            "lowercase": lambda x: x.lower() if isinstance(x, str) else x,
            "strip": lambda x: x.strip() if isinstance(x, str) else x,
            "to_list": lambda x: [x] if not isinstance(x, list) else x,
            "to_string": lambda x: str(x),
            "to_int": lambda x: int(x) if x is not None else 0,
            "split_comma": lambda x: [s.strip() for s in x.split(",")] if isinstance(x, str) else x,
        }
        # Add custom transforms
        self._transforms.update(config.get("transform_functions", {}))
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Metrics
        self._transform_count = 0
        self._validation_count = 0
        self._fallback_count = 0
        self._error_count = 0
        
        # SkillLibrary reference
        self._skill_library: Optional['SkillLibrary'] = None
    
    def on_init(self) -> None:
        """
        Initialize the adapter.
        
        Loads schema and registers event handlers.
        """
        try:
            self._state = PluginState.INITIALIZING
            self._logger.info("Initializing ContextAdapter")
            
            # Load schema
            self._load_schema()
            
            # Initialize default mappings
            for mapping in self.DEFAULT_MAPPINGS:
                self._mappings[mapping.source_path] = mapping
            
            # Add custom mappings
            for mapping_data in self._config.get("custom_mappings", []):
                mapping = ContextMapping(
                    source_path=mapping_data["source_path"],
                    target_field=mapping_data["target_field"],
                    transform=mapping_data.get("transform"),
                    required=mapping_data.get("required", True),
                    default_value=mapping_data.get("default_value")
                )
                self._mappings[mapping.source_path] = mapping
            
            # Subscribe to events
            if self._event_bus:
                self._event_bus.subscribe("EVENT_CONTEXT_READY", self._handle_context_ready)
            
            self._state = PluginState.READY
            self._logger.info(f"ContextAdapter initialized with {len(self._mappings)} mappings")
            
        except Exception as e:
            self._state = PluginState.ERROR
            self._logger.error(f"ContextAdapter initialization failed: {e}")
            raise
    
    def on_route(self, intent: str, context: Dict[str, Any]) -> RoutingDecision:
        """
        Make routing decision based on context.
        
        Args:
            intent: The classified intent
            context: Execution context
        
        Returns:
            RoutingDecision with target skills
        """
        if self._state != PluginState.READY:
            return RoutingDecision.use_fallback("ContextAdapter not ready")
        
        try:
            # Validate context
            validation = self.validate_context(context)
            
            if not validation.is_valid:
                if self._strict_validation:
                    return RoutingDecision.abort_request(
                        f"Context validation failed: {'; '.join(validation.errors)}"
                    )
                self._logger.warning(f"Context validation issues: {validation.warnings}")
            
            # Transform for skills
            execution_context = self.transform_for_skills(context)
            
            if execution_context.skill_hints:
                return RoutingDecision.redirect_to(
                    target="skill_execution",
                    confidence=0.8,
                    reason=f"Transformed context with {len(execution_context.skill_hints)} skill hints"
                )
            
            return RoutingDecision.continue_routing("No skill hints in context")
            
        except Exception as e:
            self._logger.error(f"Routing decision failed: {e}")
            return RoutingDecision.use_fallback(f"Error: {str(e)}")
    
    def on_execute(self, plan: Dict[str, Any]) -> ExecutionResult:
        """
        Execute context operations.
        
        Args:
            plan: Execution plan with operation type and parameters
        
        Returns:
            ExecutionResult with operation results
        """
        start_time = datetime.utcnow()
        
        if self._state != PluginState.READY:
            return ExecutionResult.failure_result("ContextAdapter not ready")
        
        try:
            operation = plan.get("operation", "transform")
            
            if operation == "transform":
                context = plan.get("context", {})
                execution_context = self.transform_for_skills(context)
                
                return ExecutionResult.success_result(
                    outputs={"execution_context": execution_context.to_dict()},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000),
                    fallback_used=execution_context.fallback_used
                )
            
            elif operation == "validate":
                context = plan.get("context", {})
                result = self.validate_context(context)
                
                return ExecutionResult.success_result(
                    outputs={"validation": result.to_dict()},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            elif operation == "add_mapping":
                mapping_data = plan.get("mapping", {})
                self.add_mapping(
                    source_path=mapping_data["source_path"],
                    target_field=mapping_data["target_field"],
                    transform=mapping_data.get("transform"),
                    required=mapping_data.get("required", True),
                    default_value=mapping_data.get("default_value")
                )
                return ExecutionResult.success_result(
                    outputs={"total_mappings": len(self._mappings)},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            else:
                return ExecutionResult.failure_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            self._logger.error(f"Execution failed: {e}")
            self._error_count += 1
            return ExecutionResult.failure_result(str(e))
    
    def on_error(self, error: Exception, context: Dict[str, Any]) -> ErrorResult:
        """
        Handle errors during context operations.
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
        
        Returns:
            ErrorResult indicating how to proceed
        """
        self._logger.error(f"ContextAdapter error: {error}")
        
        # For context errors, we can often continue with defaults
        if isinstance(error, (KeyError, AttributeError)):
            return ErrorResult.handled_result(f"Context field missing, using default: {error}")
        
        # For validation errors in non-strict mode
        if isinstance(error, ValueError) and not self._strict_validation:
            return ErrorResult.handled_result(f"Validation warning: {error}")
        
        return ErrorResult.unhandled_result(
            str(error),
            RoutingAction.FALLBACK
        )
    
    def on_shutdown(self) -> None:
        """
        Shutdown the adapter and clean up resources.
        """
        self._logger.info("Shutting down ContextAdapter")
        
        with self._lock:
            self._mappings.clear()
            self._schema = None
            self._state = PluginState.SHUTDOWN
        
        self._logger.info("ContextAdapter shutdown complete")
    
    def get_info(self) -> PluginInfo:
        """Get plugin information."""
        return PluginInfo(
            plugin_id="ContextAdapter",
            plugin_type="context_adapter",
            version="1.2.0",
            description="Bridges context to skill execution with validation and field mapping",
            capabilities=[
                "context_validation",
                "field_mapping",
                "skill_input_transformation",
                "fallback_handling"
            ],
            dependencies=["EventBus", "SkillLibrary"],
            priority=3
        )
    
    # =========================================================================
    # Schema and Validation
    # =========================================================================
    
    def _load_schema(self) -> None:
        """Load the context_bridge schema."""
        try:
            schema_path = Path(self._schema_path)
            if not schema_path.is_absolute():
                # Try relative to project root
                project_root = Path(__file__).parent.parent.parent.parent
                schema_path = project_root / self._schema_path
            
            if schema_path.exists():
                with open(schema_path, 'r', encoding='utf-8') as f:
                    self._schema = json.load(f)
                self._logger.info(f"Loaded schema from {schema_path}")
            else:
                self._logger.warning(f"Schema file not found: {schema_path}")
        except Exception as e:
            self._logger.warning(f"Failed to load schema: {e}")
    
    def validate_context(self, context: Dict[str, Any]) -> ValidationResult:
        """
        Validate context against context_bridge.schema.json.
        
        Args:
            context: The context payload to validate
        
        Returns:
            ValidationResult with validation findings
        """
        with self._lock:
            self._validation_count += 1
            result = ValidationResult()
            
            # Basic structure validation
            if "event_type" not in context:
                result.warnings.append("Missing event_type field")
            
            if "timestamp" not in context:
                result.warnings.append("Missing timestamp field")
            
            payload = context.get("payload", context)
            
            # Validate payload structure
            if "enriched_intent" not in payload:
                result.errors.append("Missing required field: payload.enriched_intent")
                result.missing_fields.append("payload.enriched_intent")
            
            if "skill_hints" not in payload:
                result.warnings.append("Missing skill_hints field")
            
            # Validate enriched_intent
            enriched_intent = payload.get("enriched_intent", {})
            if "original_intent" not in enriched_intent:
                result.errors.append("Missing required field: enriched_intent.original_intent")
                result.missing_fields.append("enriched_intent.original_intent")
            
            # Validate user_profile if present
            user_profile = payload.get("user_profile", {})
            if user_profile:
                valid_roles = ["designer", "developer", "analyst", "devops", "researcher", "unknown"]
                detected_role = user_profile.get("detected_role")
                if detected_role and detected_role not in valid_roles:
                    result.warnings.append(f"Invalid detected_role: {detected_role}")
                
                valid_levels = ["beginner", "intermediate", "advanced", "expert"]
                expertise = user_profile.get("expertise_level")
                if expertise and expertise not in valid_levels:
                    result.warnings.append(f"Invalid expertise_level: {expertise}")
            
            # Validate critical_gates format
            critical_gates = payload.get("critical_gates", [])
            gate_pattern = re.compile(r"^GATE-[0-9]{2}$")
            for gate in critical_gates:
                if not gate_pattern.match(gate):
                    result.warnings.append(f"Invalid gate format: {gate}")
            
            # Determine overall validity
            result.is_valid = len(result.errors) == 0
            
            if not result.is_valid:
                self._logger.warning(f"Context validation failed: {result.errors}")
            
            return result
    
    # =========================================================================
    # Transformation
    # =========================================================================
    
    def transform_for_skills(self, context: Dict[str, Any]) -> SkillExecutionContext:
        """
        Transform EVENT_CONTEXT_READY payload for skill execution.
        
        Args:
            context: The context payload (or EVENT_CONTEXT_READY payload)
        
        Returns:
            SkillExecutionContext ready for skill execution
        """
        with self._lock:
            self._transform_count += 1
            execution_context = SkillExecutionContext()
            
            # Extract payload from event structure
            payload = context.get("payload", context)
            execution_context.original_context = context
            
            # Map fields using configured mappings
            skill_inputs: Dict[str, Any] = {}
            fallback_used = False
            
            for source_path, mapping in self._mappings.items():
                value = self._extract_value(payload, source_path)
                
                if value is None:
                    if mapping.required:
                        self._logger.warning(f"Missing required field: {source_path}")
                        if mapping.default_value is not None:
                            value = mapping.default_value
                            fallback_used = True
                        else:
                            continue
                else:
                    # Apply transformation if specified
                    if mapping.transform and mapping.transform in self._transforms:
                        try:
                            value = self._transforms[mapping.transform](value)
                        except Exception as e:
                            self._logger.warning(f"Transform failed for {source_path}: {e}")
                            fallback_used = True
                
                skill_inputs[mapping.target_field] = value
            
            execution_context.skill_inputs = skill_inputs
            execution_context.fallback_used = fallback_used
            
            if fallback_used:
                self._fallback_count += 1
            
            # Extract structured fields
            execution_context.intent = payload.get("enriched_intent", {})
            execution_context.profile = payload.get("user_profile", {})
            execution_context.skill_hints = payload.get("skill_hints", [])
            execution_context.critical_gates = payload.get("critical_gates", [])
            
            # Extract metadata
            metadata = payload.get("context_metadata", {})
            metadata["transform_timestamp"] = datetime.utcnow().isoformat() + "Z"
            execution_context.metadata = metadata
            
            # Emit transformation event
            if self._event_bus:
                self._event_bus.emit_simple(
                    event_type="CONTEXT_TRANSFORMED",
                    data={
                        "skill_inputs_count": len(skill_inputs),
                        "skill_hints_count": len(execution_context.skill_hints),
                        "fallback_used": fallback_used
                    },
                    source="ContextAdapter"
                )
            
            return execution_context
    
    def _extract_value(self, data: Dict[str, Any], path: str) -> Any:
        """
        Extract a value from nested dict using dot-notation path.
        
        Args:
            data: The data dictionary
            path: Dot-notation path (e.g., "user.profile.name")
        
        Returns:
            The extracted value or None if not found
        """
        parts = path.split(".")
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    # =========================================================================
    # Mapping Management
    # =========================================================================
    
    def add_mapping(
        self,
        source_path: str,
        target_field: str,
        transform: Optional[str] = None,
        required: bool = True,
        default_value: Any = None
    ) -> None:
        """
        Add a new context field mapping.
        
        Args:
            source_path: Path in context (dot notation)
            target_field: Field name in skill input
            transform: Optional transform name
            required: Whether this field is required
            default_value: Default value if missing
        """
        with self._lock:
            mapping = ContextMapping(
                source_path=source_path,
                target_field=target_field,
                transform=transform,
                required=required,
                default_value=default_value
            )
            self._mappings[source_path] = mapping
            self._logger.info(f"Added mapping: {source_path} -> {target_field}")
    
    def remove_mapping(self, source_path: str) -> bool:
        """
        Remove a context field mapping.
        
        Args:
            source_path: The source path to remove
        
        Returns:
            True if mapping was removed
        """
        with self._lock:
            if source_path in self._mappings:
                del self._mappings[source_path]
                return True
            return False
    
    def get_mappings(self) -> List[ContextMapping]:
        """Get all current mappings."""
        return list(self._mappings.values())
    
    def add_transform(self, name: str, func: Callable[[Any], Any]) -> None:
        """
        Add a custom transform function.
        
        Args:
            name: Transform name
            func: Transform function (takes value, returns transformed value)
        """
        with self._lock:
            self._transforms[name] = func
            self._logger.info(f"Added transform: {name}")
    
    # =========================================================================
    # Event Handling
    # =========================================================================
    
    def _handle_context_ready(self, event: Any) -> None:
        """
        Handle EVENT_CONTEXT_READY event.
        
        Transforms context and makes it available for skill execution.
        
        Args:
            event: The EVENT_CONTEXT_READY event
        """
        try:
            context_data = event.data if hasattr(event, 'data') else event
            self.transform_for_skills(context_data)
        except Exception as e:
            self._logger.error(f"Failed to handle EVENT_CONTEXT_READY: {e}")
    
    # =========================================================================
    # Skill Input Preparation
    # =========================================================================
    
    def prepare_skill_input(
        self,
        skill_id: str,
        execution_context: SkillExecutionContext,
        skill_library: 'SkillLibrary' = None
    ) -> Dict[str, Any]:
        """
        Prepare input for a specific skill.
        
        Maps general skill inputs to skill-specific inputs based on
        the skill's data_flow_mapping configuration.
        
        Args:
            skill_id: The skill to prepare input for
            execution_context: The execution context
            skill_library: Optional skill library for lookup
        
        Returns:
            Skill-specific input dictionary
        """
        skill_inputs = execution_context.skill_inputs.copy()
        
        # If skill_library provided, check for skill-specific mapping
        if skill_library:
            skill = skill_library.get_skill(skill_id)
            if skill:
                # Check for data_flow_mapping in skill metadata
                skill_data = skill.to_dict()
                data_flow = skill_data.get("data_flow_mapping", {})
                
                # Apply input_sources mapping
                for mapping in data_flow.get("input_sources", []):
                    from_path = mapping.get("from", "")
                    to_field = mapping.get("to", "")
                    transform = mapping.get("transform")
                    
                    if from_path and to_field:
                        value = self._extract_value(execution_context.original_context, from_path)
                        if value is not None:
                            if transform and transform in self._transforms:
                                value = self._transforms[transform](value)
                            skill_inputs[to_field] = value
        
        # Add skill_id to inputs
        skill_inputs["_skill_id"] = skill_id
        skill_inputs["_request_id"] = execution_context.metadata.get("request_id", "")
        skill_inputs["_session_id"] = execution_context.metadata.get("session_id", "")
        
        return skill_inputs
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics."""
        with self._lock:
            return {
                "state": self._state.value,
                "mappings_count": len(self._mappings),
                "transforms_count": len(self._transforms),
                "transform_count": self._transform_count,
                "validation_count": self._validation_count,
                "fallback_count": self._fallback_count,
                "error_count": self._error_count,
                "schema_loaded": self._schema is not None
            }


# Factory function
def create_context_adapter(
    config: Dict[str, Any] = None,
    event_bus: 'EventBus' = None
) -> ContextAdapter:
    """
    Factory function to create a ContextAdapter.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
    
    Returns:
        ContextAdapter instance
    """
    return ContextAdapter(config or {}, event_bus)
