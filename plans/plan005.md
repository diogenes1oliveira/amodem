# PulseAudio Debug Tools Package

## Overview

Create a new `amodem_duplex/debugtools/` package to manage PulseAudio virtual pipes for testing audio modem streaming. The package will wrap `pactl` commands to create, list, and delete virtual audio pipes (null-sink + remap-source pairs).

## Architecture

### 1. Package Structure

```
amodem_duplex/debugtools/
├── __init__.py
├── pulseaudio_pipe.py  # Core functionality (dataclass + manager)
└── cli.py              # Click CLI interface
```

### 2. Core Components

#### Dataclass: `PulseAudioPipe`

Located in [`amodem_duplex/debugtools/pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py)

**Fields:**
- `id: str` - Normalized ID (e.g., "amodem-test-speaker1")
- `name: str` - Human-readable description (e.g., "amodem-test-speaker1-OutputPipe")
- `sink_name: str` - PulseAudio sink name
- `source_name: str` - PulseAudio source name
- `sink_module_id: int | None` - Module ID for sink (from pactl load-module)
- `source_module_id: int | None` - Module ID for source (from pactl load-module)
- `sample_rate: int` - Sample rate (default: 16000)
- `channels: int` - Number of channels (default: 1)

#### Manager Class: `PulseAudioPipeManager`

Located in [`amodem_duplex/debugtools/pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py)

**Constructor:**
```python
def __init__(
    self,
    prefix: str = "amodem-test-",
    suffix_input: str = " Mic",
    suffix_output: str = " Speaker"
)
```

**Stored Attributes:**
- `prefix: str` - Raw prefix as provided (e.g., "amodem test")
- `prefix_id: str` - Normalized prefix for IDs (e.g., "amodem-test")
- `suffix_input: str` - Raw input suffix (e.g., " Mic")
- `suffix_input_id: str` - Normalized input suffix (e.g., "-mic")
- `suffix_output: str` - Raw output suffix (e.g., " Speaker")
- `suffix_output_id: str` - Normalized output suffix (e.g., "-speaker")

**Normalization in constructor:**
- Normalize prefix → `prefix_id`
- Normalize suffix_input → `suffix_input_id`
- Normalize suffix_output → `suffix_output_id`

**Helper Methods:**

- `_normalize_name(name: str) -> str` - Static method
  - Converts nice names to ID-compatible format
  - Lowercase
  - Only allow alphanumeric, dashes, and dots
  - Replace other characters (spaces, underscores, etc.) with dashes
  - Remove consecutive dashes
  - Strip leading/trailing dashes
  - Example: "My Test Speaker 1!" → "my-test-speaker-1"
  - Example: "speaker.v2" → "speaker.v2"
  - Example: " Mic" → "mic"
  - Example: " Speaker" → "speaker"

- `_build_id(self, name: str, suffix_type: str) -> str`
  - Normalizes name first using `_normalize_name()`
  - suffix_type is either "input" or "output"
  - Returns: `{self.prefix_id}-{normalized_name}-{suffix_id}`
  - Example: prefix_id="amodem-test", name="pipe1", suffix_type="input" → "amodem-test-pipe1-mic"
  - Example: prefix_id="amodem-test", name="pipe1", suffix_type="output" → "amodem-test-pipe1-speaker"

- `_build_description(self, name: str, suffix_type: str) -> str`
  - Uses raw strings for human-readable descriptions
  - suffix_type is either "input" or "output"
  - Returns: `{self.prefix} {name}{suffix}`
  - Example: prefix="amodem test", name="pipe1", suffix_input=" Mic" → "amodem test pipe1 Mic"

**Public Methods:**

- `create(name: str, sample_rate: int = 16000, channels: int = 1) -> PulseAudioPipe`
  - Uses stored prefix/suffixes to build IDs and descriptions
  - Creates both null-sink and remap-source
  - **Sink (output):**
    - sink_name: `{prefix_id}-{normalized_name}-{suffix_output_id}`
    - description: `{prefix} {name}{suffix_output} Output`
  - **Source (input):**
    - source_name: `{prefix_id}-{normalized_name}-{suffix_input_id}`
    - master: `{sink_name}.monitor`
    - description: `{prefix} {name}{suffix_input} Input`
  - Executes: `pactl load-module module-null-sink sink_name=X sink_properties=device.description=Y`
  - Executes: `pactl load-module module-remap-source source_name=X master=X.monitor source_properties=device.description=Y`
  - Returns dataclass with IDs

- `list(pattern: str | None = None) -> list[PulseAudioPipe]`
  - Executes: `pactl list short sinks` and `pactl list short sources`
  - Filters by stored prefix_id and optional wildcard pattern (glob-style)
  - Returns list of matching pipes

- `get(identifier: str) -> PulseAudioPipe | None`
  - Searches using stored prefix_id
  - Gets by exact name or ID
  - Returns single pipe or None

- `delete(identifier: str) -> bool`
  - Searches using stored prefix_id
  - Executes: `pactl unload-module <module_id>` for both sink and source
  - Returns True if successful

- `delete_all(pattern: str | None = None) -> int`
  - Uses stored prefix_id for filtering
  - Deletes all pipes matching optional wildcard pattern
  - Returns count of deleted pipes

### 3. CLI Interface

Located in [`amodem_duplex/debugtools/cli.py`](../amodem_duplex/debugtools/cli.py)

**Command structure:** `aduplex pa <subcommand>`

**Subcommands:**

1. **`aduplex pa create NAME`**
   - Options:
     - `--sample-rate` (default: 16000)
     - `--channels` (default: 1)
     - `--prefix` (default: "amodem-test-")
     - `--suffix-input` (default: " Mic")
     - `--suffix-output` (default: " Speaker")
   - Creates pipe and prints details to stderr

2. **`aduplex pa list [PATTERN]`**
   - Options: `--prefix` (default: "amodem-test-")
   - Lists pipes, optionally filtered by pattern
   - Output to stderr

3. **`aduplex pa get IDENTIFIER`**
   - Options: `--prefix` (default: "amodem-test-")
   - Gets single pipe by name/ID
   - Output to stderr

4. **`aduplex pa delete IDENTIFIER`**
   - Options: `--prefix` (default: "amodem-test-")
   - Deletes single pipe
   - Output to stderr

5. **`aduplex pa delete-all [PATTERN]`**
   - Options: `--prefix` (default: "amodem-test-")
   - Deletes all matching pipes (with confirmation prompt)
   - Output to stderr

### 4. Integration with amodem_duplex

Update [`amodem_duplex/__main__.py`](../amodem_duplex/__main__.py) to:
- Import the CLI from `amodem_duplex.debugtools.cli`
- Add a `pa` command group
- Use click's multi-command support

**Implementation:**
```python
import click
from amodem_duplex.debugtools import cli as pa_cli

@click.group()
def main():
    """amodem_duplex - Audio Modem Duplex Communication"""
    pass

# Add PulseAudio commands
main.add_command(pa_cli.pa_group)

if __name__ == "__main__":
    main()
```

## Implementation Details

### PulseAudio Command Patterns

Based on user's examples:

**Speaker pattern (output):**
```bash
# Sink (output)
pactl load-module module-null-sink \
  sink_name=amodem-test-pipe1-speaker \
  sink_properties=device.description="amodem test pipe1 Speaker Output"

# Source (input) - monitor the sink
pactl load-module module-remap-source \
  source_name=amodem-test-pipe1-mic \
  master=amodem-test-pipe1-speaker.monitor \
  source_properties=device.description="amodem test pipe1 Mic Input"
```

**Naming convention:**
- Base ID (normalized): `{prefix_id}-{normalized_name}`
- Sink name: `{base_id}-{suffix_output_id}` (e.g., "amodem-test-pipe1-speaker")
- Source name: `{base_id}-{suffix_input_id}` (e.g., "amodem-test-pipe1-mic")
- Monitor: `{sink_name}.monitor`
- Descriptions use raw prefix and suffixes for readability

### Name Normalization Rules

The `_normalize_name()` static method should:
1. Convert to lowercase
2. Keep only alphanumeric, dashes, and dots
3. Replace other characters (spaces, underscores, special chars) with dashes
4. Remove consecutive dashes
5. Strip leading/trailing dashes

**Examples:**
- "My Test Speaker 1" → "my-test-speaker-1"
- "speaker.v2" → "speaker.v2"
- "test__name" → "test-name"
- "  edge-case  " → "edge-case"
- " Mic" → "mic"
- " Speaker" → "speaker"

### Error Handling

- Check if `pactl` is available (use `shutil.which("pactl")`)
- Parse module IDs from `pactl load-module` output (returns integer)
- Handle subprocess errors gracefully (CalledProcessError)
- Validate input parameters (name normalization, valid sample rate/channels)
- Raise appropriate exceptions with clear error messages

### Testing Strategy

Following [`AGENTS.md`](../AGENTS.md):

1. Create test skeleton in [`amodem_duplex/debugtools/tests/test_pulseaudio_pipe.py`](../amodem_duplex/debugtools/tests/test_pulseaudio_pipe.py)
2. Mock subprocess calls (don't run actual pactl commands in tests)
3. Test name normalization with various inputs:
   - Spaces, special characters, consecutive dashes
   - Edge cases: empty strings, dots, underscores
4. Test ID generation with different prefix/suffix combinations
5. Test constructor attribute storage (raw and normalized)
6. Test error handling (pactl not found, command failures)
7. Create [`amodem_duplex/debugtools/tests/test_cli.py`](../amodem_duplex/debugtools/tests/test_cli.py) for CLI
8. Use click's `CliRunner` for testing CLI commands
9. Start with skeleton (pass statements), ask before implementing

## Files to Create

1. **[`amodem_duplex/debugtools/__init__.py`](../amodem_duplex/debugtools/__init__.py)** - Empty or minimal imports
2. **[`amodem_duplex/debugtools/pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py)** - Core functionality (~200-250 lines)
3. **[`amodem_duplex/debugtools/cli.py`](../amodem_duplex/debugtools/cli.py)** - Click commands (~150-200 lines)
4. **[`amodem_duplex/debugtools/tests/__init__.py`](../amodem_duplex/debugtools/tests/__init__.py)** - Empty
5. **[`amodem_duplex/debugtools/tests/test_pulseaudio_pipe.py`](../amodem_duplex/debugtools/tests/test_pulseaudio_pipe.py)** - Manager tests
6. **[`amodem_duplex/debugtools/tests/test_cli.py`](../amodem_duplex/debugtools/tests/test_cli.py)** - CLI tests

## Files to Modify

1. **[`amodem_duplex/__main__.py`](../amodem_duplex/__main__.py)** - Add CLI integration

## Key Design Decisions

1. **Separate raw and normalized strings**: Store both human-readable (raw) and ID-compatible (normalized) versions
2. **Prefix as-is**: No automatic dash handling, use as provided
3. **Dual suffixes**: Separate input/output suffixes for flexibility
4. **Normalization method**: Static method for reusability
5. **Stored attributes**: All methods use instance attributes from constructor
6. **Strict name normalization**: Only alphanumeric, dashes, and dots allowed
7. **Auto-create both sink and source**: Simplifies usage, matches typical audio pipe needs
8. **Sample rate/channels configurable**: Allows testing different audio configs
9. **Shorter command**: `aduplex pa` instead of `aduplex debug` for convenience
10. **Store module IDs**: Required for proper cleanup with `pactl unload-module`
11. **Use subprocess**: Direct `pactl` calls, no PulseAudio Python bindings needed

## Alignment with AGENTS.md

- ✅ Keep it simple - Direct wrapper around pactl commands
- ✅ Don't over-engineer - No complex abstractions
- ✅ Use dataclasses with @dataclasses.dataclass decorator
- ✅ Type annotations on all methods
- ✅ Click for CLI (echoing to stderr per AGENTS.md)
- ✅ Mirror package structure in tests
- ✅ Start with test skeletons, ask before implementing
- ✅ Use `uv` for all Python commands
- ✅ Format with black, check with ruff

## Success Criteria

- All CLI commands work correctly
- Proper name normalization (only alphanumeric, dashes, dots)
- PulseAudio pipes created successfully with both sink and source
- List/get/delete operations work with stored prefix
- Zero linter errors (black, ruff)
- Comprehensive test coverage
- Clean integration with amodem_duplex CLI

