"""Optional Groq explanations with a deterministic Python fallback."""

from ai.facts import AiFact, Focus, build_facts
from ai.service import AnalysisResponse, analyze

__all__ = ["AiFact", "Focus", "build_facts", "AnalysisResponse", "analyze"]
