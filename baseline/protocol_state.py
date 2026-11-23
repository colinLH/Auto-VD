"""B2: validate a saved Mealy model or interpret a recorded event window."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from agent.protocols.types import Observation


class LearningError(RuntimeError):
    """Learning failed or exceeded its explicit experiment budget."""


def protocol_event_output(observation: Observation) -> str:
    """Explicit ordered message events supplied by a protocol-aware mapper.

    [] denotes confirmed silence, not missing capture or uncertain delivery.
    The adapter must correlate messages and finish its configured receive window.
    """
    evidence = observation.evidence.get("protocol_state", {})
    events = evidence.get("outputs")
    if (not observation.delivered or evidence.get("complete") is not True
            or not isinstance(events, list)
            or any(not isinstance(e, str) or not e for e in events)):
        raise LearningError("Complete, delivered protocol-event observation required")
    return json.dumps(events, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class MealyTransition:
    source: str
    input: str
    output: str
    target: str


class LearnedMealyModel:
    """Validated, total deterministic Mealy hypothesis exported by LearnLib."""

    def __init__(self, data: Mapping):
        if data.get("schema_version") != "baseline-mealy-v1":
            raise ValueError("Expected schema_version=baseline-mealy-v1")
        self.data = dict(data)
        self.alphabet = tuple(data["alphabet"])
        self.states = tuple(str(s) for s in data["states"])
        self.initial_state = str(data["initial_state"])
        if (not self.alphabet or len(set(self.alphabet)) != len(self.alphabet)
                or any(not isinstance(s, str) or not s for s in self.alphabet)):
            raise ValueError("Model alphabet must contain unique nonempty names")
        if not self.states or len(set(self.states)) != len(self.states) or self.initial_state not in self.states:
            raise ValueError("Invalid model states or initial state")
        self.transitions = tuple(MealyTransition(str(t["source"]), t["input"],
                                                t["output"], str(t["target"]))
                                 for t in data["transitions"])
        self._index = {}
        for transition in self.transitions:
            key = (transition.source, transition.input)
            if (transition.source not in self.states or transition.target not in self.states
                    or transition.input not in self.alphabet or not isinstance(transition.output, str)
                    or key in self._index):
                raise ValueError("Invalid or nondeterministic transition")
            self._index[key] = transition
        if len(self._index) != len(self.states) * len(self.alphabet):
            raise ValueError("Model must define every state/input transition")

    @classmethod
    def load(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(value)
        return cls(json.loads(Path(value).read_text(encoding="utf-8")))
