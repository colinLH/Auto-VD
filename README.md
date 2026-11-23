# Auto-VD: passive analysis components

This source release contains the parts of Auto-VD that interpret protocol
formats, recorded observations, and saved models. It is not the complete
device-testing system or an end-to-end reproduction of the four baselines.

| Component | Implementation included |
| --- | --- |
| System | Declared wire-layout decoding, observation types, state normalization, and the monitor report JSON schema |
| B1 - LLMIF | Retrieve message descriptions from a local specification PDF; parse existing format answers and relationship verdicts |
| B2 - protocol state learning | Validate an exported LearnLib Mealy model and interpret recorded protocol events; no active learning or simulation |
| B3 - Beehive | Classify recorded observations using the applicable Zigbee or Z-Wave anomaly rules |
| B4 - HubFuzzer | Classify recorded ACK/Report evidence, keeping incomplete observations and unconfirmed symptoms distinct |

The modules do not contact devices, call an online model, or generate test
traffic. No simulator, reference target, experiment, result, device inventory,
paper, or packet capture is distributed. Reading a PDF with B1 requires the
optional dependency in `baseline/requirements-llmif.txt`; the remaining
modules use Python's standard library.
