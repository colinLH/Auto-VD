"""Evidence returned by low-level protocol transports."""
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Observation:
    status: str
    delivered: bool
    response: Any = None
    state: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
