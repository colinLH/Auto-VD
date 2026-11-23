"""B1: parse existing LLMIF format and relationship answers."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class InferredField:
    name: str
    data_type: str
    # Unknown/variable lengths and semantic types stay unknown, never guessed.
    size_bits: int | None = None


def parse_format_answer(answer: str) -> tuple[InferredField, ...]:
    """Parse main-paper JSON or supplementary list literals without execution.

    The original prompt's malformed ``(name: type)`` example is *not* rewritten.
    Malformed answers fail explicitly instead of inventing message fields.
    """
    text = answer.strip()
    if len(text) > 100_000:
        raise ValueError("LLMIF format answer is too large")
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:python|json)?\s*\n?(.*?)\n?```", text, re.S)
        if not match:
            raise ValueError("Invalid fenced LLMIF format answer")
        text = match.group(1).strip()
    try:
        parsed = json.loads(text) if text.startswith("{") else ast.literal_eval(text)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError("LLMIF format answer is not a Python literal") from exc
    if isinstance(parsed, dict):
        # Main-paper Figure 3a uses {message: {field: type}}; the released
        # protocol-general template uses [(field, type)]. Both are supported.
        if len(parsed) == 1 and isinstance(next(iter(parsed.values())), (dict, list)):
            parsed = next(iter(parsed.values()))
        if isinstance(parsed, dict):
            parsed = list(parsed.items())
    if not isinstance(parsed, (list, tuple)) or len(parsed) > 1024:
        raise ValueError("LLMIF format answer must be a bounded list of field pairs")
    result = []
    for pair in parsed:
        if isinstance(pair, dict) and len(pair) == 1:
            pair = next(iter(pair.items()))
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("Every inferred field requires a name and data type")
        name, data_type = pair
        if not isinstance(name, str) or not isinstance(data_type, str) or not name or not data_type:
            raise ValueError("Inferred field names and data types must be nonempty strings")
        width = re.fullmatch(r"\s*(\d+)\s*(bits?|bytes?)\s*", data_type, re.I)
        primitive = re.fullmatch(r"(?:u?int|enum|bitmap|map|data)(8|16|24|32|40|48|56|64)(?:_t|s)?", data_type, re.I)
        bits = (int(width[1]) * (8 if width[2].lower().startswith("byte") else 1) if width
                else int(primitive[1]) if primitive else 8 if data_type.lower() in {"bool", "boolean"} else None)
        result.append(InferredField(name, data_type, bits))
    return tuple(result)


def dependency_verdict(answer: str) -> bool:
    """Use the last explicit verdict, avoiding positive words inside reasoning."""
    matches = re.findall(r"\bStatement\s+(does\s+not|does)\s+hold\b", answer, re.I)
    if not matches:
        raise ValueError("LLMIF dependency answer has no explicit final verdict")
    return matches[-1].lower() == "does"
