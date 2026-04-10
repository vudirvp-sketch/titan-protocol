class PipelineError(Exception):
    """Base error for pipeline failures."""
    def __init__(self, message: str, phase: str, gate: str = ""):
        self.phase = phase
        self.gate = gate
        super().__init__(f"[{phase}:{gate}] {message}" if gate else f"[{phase}] {message}")


class GateFailedError(PipelineError):
    """A gate check failed within a pipeline phase."""
    def __init__(self, message: str, phase: str, gate: str):
        super().__init__(message, phase=phase, gate=gate)


class PhaseAbortedError(PipelineError):
    """A phase was aborted due to an unrecoverable condition."""
    def __init__(self, message: str, phase: str):
        super().__init__(message, phase=phase)


class RLMTerminationError(PipelineError):
    """RLM (Run-Length Monitor) terminated execution."""
    def __init__(self, message: str, phase: str, reason: str = ""):
        self.reason = reason
        super().__init__(message, phase=phase)
