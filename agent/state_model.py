"""Bounded observable state abstractions; raw data remains in the evidence log."""
import hashlib
import json
import math

VOLATILE = {"timestamp", "tsn", "sequence", "sequence_number", "epoch", "reset_epoch"}
DEFAULT_ATTRIBUTES = {"on_off", "current_level", "occupancy", "lock_state", "alarm_count",
                      "zone_status", "present_value", "measured_value", "group_count", "scene_count"}


def flatten(snapshot):
    out = {}
    for endpoint, clusters in (snapshot or {}).items():
        if not isinstance(clusters, dict):
            continue
        for cluster, attributes in clusters.items():
            if not isinstance(attributes, dict):
                continue
            for attribute, record in attributes.items():
                value = record.get("value") if isinstance(record, dict) else record
                out[f"{endpoint}.{cluster}.{attribute}"] = value
    return out


def bounded_class(value, descriptor=None):
    if value is None:
        return None
    descriptor = descriptor or {}
    if isinstance(value, bool):
        return "true" if value else "false"
    if descriptor.get("values"):
        return str(value) if value in descriptor["values"] else "other"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        cuts = sorted(set(descriptor.get("thresholds", [0, 1, 254])))
        for i, cut in enumerate(cuts):
            if value <= cut:
                return f"bin:{i}"
        return f"bin:{len(cuts)}"
    if isinstance(value, (list, tuple, dict, str)):
        return "empty" if len(value) == 0 else "nonempty"
    return None


def canonical_state(snapshot, profile="", descriptors=None, relevant=None):
    descriptors = descriptors or {}
    relevant = set(relevant) if relevant is not None else DEFAULT_ATTRIBUTES
    facts, unknown = {}, []
    for path, value in sorted(flatten(snapshot).items()):
        name = path.rsplit(".", 1)[-1]
        if name in VOLATILE or not (name in relevant or path in relevant or path in descriptors):
            continue
        category = bounded_class(value, descriptors.get(path))
        if category is None:
            unknown.append(path)
        else:
            facts[path] = category
    for path in descriptors:
        if path not in facts and path not in unknown:
            unknown.append(path)
    # Unknown/missing values do not themselves define a novel state.
    key = hashlib.sha256(json.dumps([profile, facts], sort_keys=True).encode()).hexdigest()[:20] if facts else None
    return {"key": key, "facts": facts, "unknown": sorted(unknown), "validated": bool(facts) and not unknown}


def predicates_match(snapshot, predicates):
    facts = flatten(snapshot)
    for predicate in predicates:
        path = predicate["path"]
        if path not in facts or facts[path] is None:
            return False
        if predicate.get("op", "eq") == "eq":
            if facts[path] != predicate["value"]:
                return False
        elif predicate["op"] == "class":
            if bounded_class(facts[path], predicate.get("descriptor")) != predicate["value"]:
                return False
        else:
            return False
    return True


RESPONSE_CLASSES = {"SUCCESS", "FAILURE", "NOT_AUTHORIZED", "UNSUP_COMMAND", "UNSUP_CLUSTER",
                    "INVALID_VALUE", "INVALID_DATA_TYPE", "MALFORMED_COMMAND", "TIMEOUT"}


def response_class(result):
    if result.get("status") == "timeout":
        return "TIMEOUT"
    codes = result.get("status_codes", [])
    return ",".join(sorted({c if c in RESPONSE_CLASSES else "OTHER" for c in codes})) or "REPLY"
