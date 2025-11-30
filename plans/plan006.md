# Fix PulseAudio Virtual Pipes - Simple Approach

**CRITICAL: This plan follows strict TDD methodology per [AGENTS.md](../AGENTS.md)**

## Context

The pw-cli approach in [reports/report005.md](../reports/report005.md) doesn't work. User wants to go back to PulseAudio/pactl but avoid the spaces issue entirely.

## The Simple Solution

**Key Insight:** Always pass names with underscores and dashes - no normalization needed. Use the same string for both the device name AND description. No escaping problems!

### Example

Instead of:

- sink_name: `amodem-test-pipe1-speaker`
- description: `"amodem test pipe1 Speaker Output"` ← causes problems!

Do:

- sink_name: `amodem-test-pipe1-speaker`
- description: `amodem-test-pipe1-speaker` ← no normalization, no problems!

The names are clear enough without fancy descriptions.

## Implementation Plan

**⚠️ CRITICAL TDD REQUIREMENT (per AGENTS.md):**

1. **ALWAYS write tests FIRST**
2. **Tests should fail initially** (red)
3. **Then implement to make them pass** (green)
4. **Actually run tests** - don't just say "ready for testing"
5. **Follow this order strictly**: Test skeleton → Test implementation → Run test (should fail) → Implementation → Run test (should pass)

### Phase 1: Create Test Skeleton FIRST

**File: test_pulseaudio_pipe.py**

**IMPORTANT: Test against real running PulseAudio - NO MOCKS!**

Create test file with:

- Header: `# mypy: disable-error-code="no-untyped-def"`
- Import statements
- Test class: `TestPulseAudioPipeManager`
- Manager fixture at TOP of class that creates a real `PulseAudioPipeManager` instance
- Cleanup fixture to ensure all test pipes are deleted after each test
- All test method signatures with single `pass` statement
- NO comments (test names are descriptive)

Test methods to create:

- `test_create_pipe_creates_real_devices`
- `test_create_pipe_returns_pipe_with_module_ids`
- `test_delete_pipe_removes_devices`
- `test_list_all_returns_created_pipes`
- `test_get_finds_pipe_by_name`
- `test_delete_all_removes_all_matching_pipes`
- `test_pactl_not_available_raises_error`
- `test_created_devices_visible_in_pactl_list`

**STOP HERE and run:** `uv run pytest amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py -v`

All tests should pass (they just have `pass` statements).

### Phase 2: Implement Tests with Expectations

**CRITICAL: Test against real PulseAudio - NO MOCKS!**

For EACH test method:

1. **Write test implementation** with setup/act/verify blocks (NO comments for block labels)
2. **Use real PulseAudio** - actually create/delete pipes
3. **Verify using real pactl commands** - check that devices exist
4. **Run the test**: `uv run pytest path/to/test.py::TestClass::test_method -v`
5. **Test should FAIL** (implementation doesn't exist yet)
6. **Document the failure** - what's missing?

Example test structure:

```python
def test_create_pipe_creates_real_devices(self, manager):
    pipe = manager.create("test1", sample_rate=16000, channels=1)

    assert pipe.sink_name == "amodem-test-test1-speaker"
    assert pipe.source_name == "amodem-test-test1-mic"
    assert pipe.sink_module_id is not None
    assert pipe.source_module_id is not None
```

Example fixture structure (like pipewire tests would have):

```python
@pytest.fixture
def manager(self):
    mgr = PulseAudioPipeManager(prefix="amodem-test-pytest")
    yield mgr
    # Cleanup: delete all test pipes
    mgr.delete_all()
```

### Phase 3: Create Implementation Skeleton

**File: pulseaudio_pipe.py**

Create with:

- Dataclass definition
- Manager class with method signatures only
- Docstrings for each method
- NO implementation yet (just `pass` or `raise NotImplementedError`)

**Run tests again** - should still fail but now with different errors.

### Phase 4: Implement to Make Tests Pass

Implement methods ONE AT A TIME in this order:

**4.1 Implement `__init__()`**

- Write implementation (check pactl availability)
- Run test: `uv run pytest ... -k test_pactl_not_available`
- Should PASS

**4.2 Implement `_create_null_sink()`**

- Write implementation using pactl
- Run test: `uv run pytest ... -k test_create_pipe_calls_pactl`
- Should start passing module-null-sink assertions

**4.3 Implement `_create_remap_source()`**

- Write implementation using pactl
- Run test: `uv run pytest ... -k test_create_pipe`
- Should fully pass create tests

**4.4 Implement `_list_nodes()`**

- Write implementation using pactl list short
- Run test: `uv run pytest ... -k test_list_all`
- Should PASS

**4.5 Implement `_unload_module()`**

- Write implementation
- Run test: `uv run pytest ... -k test_delete`
- Should PASS

**4.6 Implement `create()`, `delete()`, `get()`, `list_all()`, `delete_all()`**

- Write implementations
- Run full test suite: `uv run pytest amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py -v`
- All should PASS

### Phase 5: Update CLI and Integration

**5.1 Update CLI implementation**

- Rename pw_group → pa_group in cli.py
- Update imports from `pipewire_pipe` to `pulseaudio_pipe`
- Update help text to say "PulseAudio"

**5.2 Update **main**.py and **init**.py**

- Update imports
- Update command registration to use `pa_group`

**5.3 Manual CLI testing** (user will test)

- Test: `uv run python -m amodem_duplex pa --help`
- Test: `uv run python -m amodem_duplex pa create test1`
- Test: `uv run python -m amodem_duplex pa list`
- Test: `uv run python -m amodem_duplex pa delete test1`

### Phase 6: Clean Up Old Files

Only AFTER all tests pass:

- Delete `pipewire_pipe.py`
- Delete `test_pipewire_pipe.py`
- Run full test suite one more time
- Run linters: `uv run ruff check` and `uv run black --check`

### Step 1: Revert to PulseAudio Terminology

Rename everything back to PulseAudio:

**File names:**

- `pipewire_pipe.py` → `pulseaudio_pipe.py`
- `test_pipewire_pipe.py` → `test_pulseaudio_pipe.py`

**Class names:**

- `PipeWirePipe` → `PulseAudioPipe`
- `PipeWirePipeManager` → `PulseAudioPipeManager`

**CLI naming:**

- `pw_group` → `pa_group`
- Command: `aduplex pa create ...`

### Step 2: Update Implementation in pulseaudio_pipe.py

**2.1 Update dataclass**

```python
@dataclasses.dataclass
class PulseAudioPipe:
    id: str
    name: str
    sink_name: str
    source_name: str
    sink_module_id: int | None
    source_module_id: int | None
    sample_rate: int
    channels: int
```

**2.2 Simplify description building**

Don't normalize names - just use them as-is with underscores and dashes:

```python
def _build_description(self, name: str, suffix_type: str) -> str:
    """Build description - just use the entity name (no normalization)."""
    return self._build_entity_name(name, suffix_type)
```

Or even simpler - don't have a separate method, just use entity_name directly as the description.

**2.3 Implement \_create_null_sink**

```python
def _create_null_sink(
    self,
    sink_name: str,
    sample_rate: int,
    channels: int
) -> int:
    """Create null sink using pactl load-module."""
    args = [
        "pactl", "load-module", "module-null-sink",
        f"sink_name={sink_name}",
        f"sink_properties=device.description={sink_name}",  # Same as name!
        f"rate={sample_rate}",
        f"channels={channels}",
    ]

    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return int(result.stdout.strip())
```

**2.4 Implement \_create_remap_source**

```python
def _create_remap_source(
    self,
    source_name: str,
    master: str
) -> int:
    """Create remap source using pactl load-module."""
    args = [
        "pactl", "load-module", "module-remap-source",
        f"source_name={source_name}",
        f"master={master}",
        f"source_properties=device.description={source_name}",  # Same as name!
    ]

    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return int(result.stdout.strip())
```

**2.5 Implement \_unload_module**

```python
def _unload_module(self, module_id: int | None) -> bool:
    """Unload module using pactl."""
    if module_id is None:
        return False
    try:
        subprocess.run(
            ["pactl", "unload-module", str(module_id)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False
```

**2.6 Implement listing using pactl**

Use `pactl list short` commands for all listing operations:

```python
def _list_nodes(self) -> dict[int, dict[str, str]]:
    """List all sinks and sources using pactl."""
    nodes = {}

    # Get sinks
    result = subprocess.run(
        ["pactl", "list", "sinks", "short"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2:
            sink_id = int(parts[0])
            sink_name = parts[1]
            nodes[sink_id] = {
                "node.name": sink_name,
                "media.class": "Audio/Sink",
            }

    # Get sources
    result = subprocess.run(
        ["pactl", "list", "sources", "short"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2:
            source_id = int(parts[0])
            source_name = parts[1]
            nodes[source_id] = {
                "node.name": source_name,
                "media.class": "Audio/Source",
            }

    return nodes
```

**2.7 Update create() method**

```python
def create(self, name: str, sample_rate: int = 16000, channels: int = 1) -> PulseAudioPipe:
    # No normalization - use names with underscores/dashes as-is
    if not name:
        raise ValueError("name cannot be empty")

    sink_name = self._build_entity_name(name, "output")
    source_name = self._build_entity_name(name, "input")

    # Create null sink
    sink_module_id = self._create_null_sink(sink_name, sample_rate, channels)

    # Create remap source (monitor the sink)
    source_module_id = self._create_remap_source(source_name, f"{sink_name}.monitor")

    return PulseAudioPipe(
        id=self._build_pipe_id(name),
        name=name,
        sink_name=sink_name,
        source_name=source_name,
        sink_module_id=sink_module_id,
        source_module_id=source_module_id,
        sample_rate=sample_rate,
        channels=channels,
    )
```

**2.8 Update delete() method**

```python
def delete(self, identifier: str) -> bool:
    pipe = self.get(identifier)
    if pipe is None:
        return False

    sink_ok = self._unload_module(pipe.sink_module_id)
    source_ok = self._unload_module(pipe.source_module_id)

    return sink_ok or source_ok
```

**2.9 Update **init** to check for pactl**

```python
def __init__(
    self,
    prefix: str = "amodem-test",  # Use underscores/dashes as-is
    suffix_input: str = "mic",     # Simple identifier, underscores/dashes ok
    suffix_output: str = "speaker", # Simple identifier, underscores/dashes ok
) -> None:
    self.prefix = prefix
    self.suffix_input = suffix_input
    self.suffix_output = suffix_output

    # Check pactl availability
    self._pactl_path = shutil.which("pactl")
    if not self._pactl_path:
        raise RuntimeError("pactl is not available in PATH")
```

### Step 3: Update CLI

**File: cli.py**

- Rename `pw_group` → `pa_group`
- Update help text to say "PulseAudio" instead of "PipeWire"
- Update imports from `pipewire_pipe` to `pulseaudio_pipe`

**File: **main**.py**

- Update imports from `pw_cli` → `pa_cli` (or keep naming, doesn't matter)
- Update command registration to use `pa_group`

**File: **init**.py**

- Update exports: `PipeWirePipe` → `PulseAudioPipe`
- Update exports: `PipeWirePipeManager` → `PulseAudioPipeManager`

### Step 4: Update Tests

**File: test_pulseaudio_pipe.py**

- Update all class names (PipeWire → PulseAudio)
- **NO MOCKS** - test against real PulseAudio using pactl commands
- Create real pipes and verify they exist
- Test with names using underscores/dashes (no normalization)
- Use manager fixture similar to pipewire tests (real instance + cleanup)

### Step 5: Delete Old Files

Remove:

- `amodem_duplex/debugtools/pipewire_pipe.py` (replaced by pulseaudio_pipe.py)
- `amodem_duplex/tests/debugtools/test_pipewire_pipe.py` (replaced by test_pulseaudio_pipe.py)

## Files to Create/Modify

**Create:**

1. `amodem_duplex/debugtools/pulseaudio_pipe.py` - Core implementation
2. `amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py` - Tests

**Modify:** 3. `amodem_duplex/debugtools/cli.py` - Rename pw_group → pa_group 4. `amodem_duplex/__main__.py` - Update imports 5. `amodem_duplex/debugtools/__init__.py` - Update exports

**Delete:** 6. `amodem_duplex/debugtools/pipewire_pipe.py` 7. `amodem_duplex/tests/debugtools/test_pipewire_pipe.py`

## Key Simplifications

1. **Names with underscores/dashes** - pass names as-is, no normalization
2. **Same string for name and description** - no escaping needed at all
3. **Back to PulseAudio terminology** - it's just pactl anyway with PipeWire compatibility
4. **Standard pactl commands** - module-null-sink and module-remap-source
5. **Module IDs for deletion** - simple integer tracking
6. **Use pactl for everything** - list sinks/sources, load/unload modules, no pw-dump

## Example Usage

```bash
# Create with default prefix/suffix
aduplex pa create pipe1
# Creates: amodem-test-pipe1-speaker (sink) and amodem-test-pipe1-mic (source)

# Create with custom prefix
aduplex pa create pipe2 --prefix myapp
# Creates: myapp-pipe2-speaker and myapp-pipe2-mic

# List all
aduplex pa list

# Delete
aduplex pa delete pipe1
```

Names use underscores and dashes as provided, no normalization needed!

## Success Criteria

1. ✅ `aduplex pa create test1` works without errors
2. ✅ Devices appear in `pactl list sinks short` and `pactl list sources short`
3. ✅ Devices appear in pavucontrol
4. ✅ Browser can select devices in audio settings
5. ✅ `aduplex pa delete test1` removes devices completely
6. ✅ All tests pass against real PulseAudio (no mocks)
7. ✅ No background processes needed
8. ✅ No shell escaping issues whatsoever
9. ✅ Uses pactl for all operations (create, delete, list)
