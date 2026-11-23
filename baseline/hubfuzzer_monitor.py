"""B4: classify recorded ACK/Report evidence without a transport."""
from __future__ import annotations

from agent.protocols.types import Observation


def response_signals(observation: Observation | None):
    if observation is None:
        return {"ack_received": None, "report_received": None, "window_complete": False}
    raw = observation.evidence.get("hubfuzzer_monitor", {})
    if not isinstance(raw, dict):
        raise ValueError("hubfuzzer_monitor evidence must be an object")
    keys = ("ack_received", "report_received", "window_complete", "report_expected", "network_reliable", "awake")
    if any(key in raw and type(raw[key]) is not bool for key in keys):
        raise ValueError("ACK/Report monitor evidence fields must be explicit booleans")
    return {key: raw.get(key, False if key == "window_complete" else None) for key in keys}


def assess_response(observation, *, reset_observation=None, known_valid_reset=False):
    signals = response_signals(observation)
    result = {"signals": signals, "classification": "unknown", "anomalies": [],
              "confirmation": "not a confirmed crash or vulnerability", "needs_reset_check": False}
    if not signals["window_complete"]:
        result["reason"] = "ACK/Report capture is absent or incomplete"
    elif signals.get("awake") is False or signals.get("network_reliable") is False:
        result["reason"] = "sleep or unreliable transport prevents crash attribution"
    elif signals["report_received"] is True:
        result.update(classification="responsive", reason="Report received (Figure 6a)")
    elif signals["ack_received"] is False:
        result.update(classification="no_ack_candidate", reason="No ACK in a completed capture (Figure 6c); replay required",
                      anomalies=["HubFuzzer:no_ack_candidate"])
    elif signals["ack_received"] is True and signals["report_received"] is False:
        result.update(classification="ambiguous", needs_reset_check=True,
                      reason="ACK without Report cannot distinguish discard from crash (Figure 6b/d)")
        if reset_observation is not None:
            reset = response_signals(reset_observation)
            result["reset_signals"] = reset
            if reset["window_complete"] and reset["report_received"] is True:
                result.update(classification="responsive_after_reset", needs_reset_check=False,
                              reason="Known reset received a Report; mutant silence is not crash evidence")
            elif (known_valid_reset and reset["window_complete"] and reset["report_received"] is False
                    and reset["report_expected"] is True and reset["awake"] is True
                    and reset["network_reliable"] is True):
                result.update(classification="no_report_after_valid_reset_candidate", needs_reset_check=False,
                    reason="Expected Report absent after a known-valid reset (Section 5.5); replay required",
                    anomalies=["HubFuzzer:no_report_after_valid_reset_candidate"])
            else:
                result["reason"] = "Reset Report expectation, capture, wakefulness or transport reliability is unverified"
    else:
        result["reason"] = "Capture has no conclusive ACK/Report combination"
    return result
