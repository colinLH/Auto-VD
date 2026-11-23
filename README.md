# Auto-VD: Read-Only Analysis of IoT Protocol Data

Use these Python modules to decode a payload against a known layout, compare
recorded device states, or interpret what a response establishes. For example,
a radio acknowledgement can establish delivery without establishing that the
application executed a command.

This is the **read-only subset** of Auto-VD and its four comparison methods.
The modules take local files or Python objects as input. They do not contact
devices, call an online model, or run the end-to-end experiments.

[Running environment](#running-environment) | [Quick start](#quick-start) |
[System components](#system-components) | [Baseline methods](#baseline-methods) |
[Troubleshooting](#troubleshooting)

```text
Input you supply                  Reader                     What you get
Layout and payload bytes       -> WireSchema              -> named fields and byte offsets
Attribute snapshot             -> canonical_state         -> comparable facts and unknowns
Specification or saved answer  -> B1                      -> source passages or inferred fields
Exported Mealy model           -> B2                      -> validated transitions
Recorded protocol evidence     -> B2 / B3 / B4            -> event list / symptoms / ACK-Report classification
```

## Running Environment

Use **CPython 3.11 or 3.12** with `venv`. Git is needed to clone the source.
The core modules use only the Python standard library. No radio, gateway,
database, API key, or Java installation is needed. Once the source and any
optional dependency are on disk, analysis works offline.

### Step 1: Clone the repository and create an environment

```sh
git clone https://github.com/colinLH/Auto-VD.git
cd Auto-VD
```

On macOS or Linux:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
```

On Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If using Python 3.11, substitute `python3.11` or `py -3.11` when creating the
environment. Run the remaining commands from the checkout root, alongside
`agent/` and `baseline/`. These are importable source modules, not an
installable application; there is no `pip install .` step or service to start.

### Step 2: Check the core installation

```sh
python --version
python -c "from agent.protocols.schema import WireSchema; from baseline.hubfuzzer_monitor import assess_response; print('Auto-VD ready')"
```

The second command should print `Auto-VD ready` in a fresh environment, before
installing anything with `pip`.

### Step 3: Enable PDF reading (B1 only, optional)

```sh
python -m pip install -r baseline/requirements-llmif.txt
python -c "import pypdf; print(pypdf.__version__)"
```

The version should be `6.10.0`, as pinned in the
[PDF requirements](baseline/requirements-llmif.txt). Skip this step if you
only parse saved LLMIF answers, load a model, or classify an observation.

## Quick Start

Start `python` in the checkout root and try either example. The literal values
illustrate the API; they are not device measurements or evaluation results.

**Decode a field from two bytes.** Supply the layout and byte order rather
than asking the decoder to guess them. Offsets and sizes are in bytes.

```python
from agent.protocols.schema import WireSchema

schema = WireSchema([{"name": "reading", "kind": "uint", "size": 2}], byteorder="little")
field, = schema.decode_layout(bytes.fromhex("2c 01"))
print(field["name"], field["offset"], field["size"], field["value"])
# reading 0 2 300
```

**Distinguish silence from failure.** In this record, delivery was confirmed
and the observation window closed without an application Report. B2 preserves
the empty list of protocol events. B4 has an ACK but no Report, so it cannot
tell whether the command was discarded or the device stopped responding.

```python
from agent.protocols.types import Observation
from baseline.protocol_state import protocol_event_output
from baseline.hubfuzzer_monitor import assess_response

record = Observation(
    status="recorded",
    delivered=True,
    evidence={
        "protocol_state": {"complete": True, "outputs": []},
        "hubfuzzer_monitor": {
            "window_complete": True, "ack_received": True, "report_received": False,
        },
    },
)
print(protocol_event_output(record))               # []
print(assess_response(record)["classification"])   # ambiguous
```

## System Components

| Component | Input | Output and interpretation |
| --- | --- | --- |
| [Wire layout](agent/protocols/schema.py) | Ordered field definitions and payload bytes | `WireSchema.decode_layout()` returns each present field's name, byte offset, size, wire bytes, and value. Supports fixed sizes, length prefixes, and conditions referring to earlier fields. Rejects truncation and trailing bytes. No protocol layout catalog is bundled. |
| [Observation](agent/protocols/types.py) | A status and delivery flag, with optional response, state, and evidence | `Observation` keeps transport delivery separate from application evidence. It holds a record; it does not collect one. |
| [State normalization](agent/state_model.py) | A snapshot nested by endpoint, cluster, and attribute | `canonical_state()` returns comparable `facts`, a state `key`, and `unknown` paths. Volatile fields such as timestamps are ignored. If there are no known facts the key is `None`. `predicates_match()` checks recorded values against supplied conditions. |
| [Monitor report schema](docs/monitor_report.schema.json) | A monitor report in the `monitor-v1` format | The JSON Schema defines the expected identity, state, liveness, observations, evaluator input, uncertainty, and source references. It is a data contract, not a report generator or an example result. |

## Baseline Methods

Each entry describes the part of the method available here and the artifact
you must supply. The four modules can be used independently.

### B1: LLMIF - specification text and saved answers

- [Specification reader](baseline/llmif_spec.py): `retrieve_spec_descriptions()`
  reads an unencrypted, text-bearing PDF with outline bookmarks. Its default
  selects child sections of headings matching `commands\s+received`; use
  `section_pattern` and `selection="matching"` if the command headings themselves
  are the entries of interest. The result includes message text, physical page
  ranges, and the source hash. Adjacent sections may share a boundary page.
- [Answer parser](baseline/llmif.py): `parse_format_answer()` converts an
  existing answer into field names, type names, and bit widths. Unknown widths
  remain `None`; parsing is not proof that a proposed format is correct.
  `dependency_verdict()` reads the last explicit `Statement does hold` or
  `Statement does not hold` verdict. Neither function calls a model.

```python
from baseline.llmif import parse_format_answer

fields = parse_format_answer('{"Report": {"level": "uint8", "label": "string"}}')
print([(f.name, f.size_bits) for f in fields])
# [('level', 8), ('label', None)]
```

### B2: Protocol state learning - model and event validation

[`LearnedMealyModel.load()`](baseline/protocol_state.py) accepts a mapping or a
JSON file in the project's `baseline-mealy-v1` format. Supply `alphabet`,
`states`, `initial_state`, and `transitions` in addition to `schema_version`.
Each transition has a `source`, `input`, `output`, and `target`. The loader
checks that every state/input pair has exactly one transition and references
valid states. It **validates an existing model**; it does not run LearnLib or
learn from a device. `protocol_event_output()` returns a JSON string preserving
event order and duplicates. A complete, delivered window can produce `"[]"`;
an incomplete window or unconfirmed delivery raises `LearningError` instead.

### B3: Beehive - recorded anomaly labels

[`anomaly_events(evidence, protocol=...)`](baseline/beehive.py) reads an evidence
dictionary and returns a list of symptom labels. It requires `capture_valid`
to be `True`; a timeout alone is not a valid capture. The default is Zigbee.
With `protocol="zwave"`, only the long-silence and response-delay rules apply,
not Zigbee-specific beacon or network-key rules. An empty list means no
supported symptom was identified, not that the device is known to be healthy.

### B4: HubFuzzer - ACK and Report classification

[`assess_response()`](baseline/hubfuzzer_monitor.py) reads the
`hubfuzzer_monitor` fields of an `Observation` and returns the `classification`,
`reason`, and the signals used. A Report in a reliable, completed window can
support `responsive`; an ACK without a Report is `ambiguous`; an incomplete
window stays `unknown`. An optional second, already-recorded observation can
inform the classification. The module does not perform a reset, and its
symptom labels do not confirm a crash.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `No module named 'agent'` or `'baseline'` | Start Python from the checkout root, not from inside either package. |
| B1 cannot import `pypdf` | Install the optional requirements with the same `python` that will open the PDF. No other component needs it. |
| B1 finds no matching PDF sections | Inspect the document's bookmarks, choose a matching heading pattern and selection mode, and check that the pages contain extractable text. The reader does not perform OCR. |
| B3 returns no labels or B4 returns `unknown` | Check the recorded capture validity or window-completion fields. Missing evidence cannot be interpreted as a negative result. |

This release does not include device drivers, traffic generation, simulators,
reference targets, experiment runners or results, device inventories, papers,
or packet captures.
