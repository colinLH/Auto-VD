"""B3: classify symptoms in recorded evidence without generating traffic."""


def anomaly_events(evidence, protocol="zigbee"):
    """Table 1 observation rules; output symptoms, never confirmed bugs.

    Absence of a field means unknown. Traffic classifiers and key validation
    must be supplied by the capture adapter; receiving a timeout is insufficient.
    """
    result = []
    if evidence.get("capture_valid") is not True:
        return result
    quiet = evidence.get("no_response_seconds")
    if isinstance(quiet, (int, float)) and quiet > 600:
        result.append("1:no_response_over_10_minutes")
    if evidence.get("beacon_request") is True:
        result.append("2:beacon_request")
    rejoin = evidence.get("beacon_request_duration_seconds")
    if isinstance(rejoin, (int, float)) and rejoin >= 600:
        result.append("3:continual_reconnection")
    for key, label in (("unencrypted_packet", "4:unencrypted_packet"),
                       ("encrypted_packet_without_mic", "5:missing_mic"),
                       ("network_key_plaintext_verified", "6:plaintext_network_key"),
                       ("network_key_known_key_verified", "7:known_key_transport"),
                       ("high_rssi", "8:high_rssi"),
                       ("sleep_mode_packet", "10:sleep_mode"),
                       ("relay_list_changed", "11:relay_list_changed")):
        if evidence.get(key) is True:
            result.append(label)
    latency = evidence.get("response_latency_seconds")
    if isinstance(latency, (int, float)) and latency > 3:
        result.append("9:response_delay_over_3_seconds")
    if protocol.lower().replace("-", "") == "zwave":
        # Beacon/MIC/network-key/relay-list rules are Zigbee-specific. Encryption
        # security anomalies require an independent Z-Wave capture classifier.
        result = [event for event in result if event.startswith(("1:", "9:"))]
    return result
