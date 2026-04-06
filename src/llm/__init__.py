"""
TITAN FUSE Protocol - LLM Integration Module

Provides real LLM integration using z-ai-web-dev-sdk.
Implements the llm_query specification from PROTOCOL.md v3.2.
"""

from .llm_client import LLMClient, QueryResult
from .surgical_patch import SurgicalPatchEngine, PatchResult

__all__ = ['LLMClient', 'QueryResult', 'SurgicalPatchEngine', 'PatchResult']
