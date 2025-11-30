# Debug and Fix PulseAudio Pipes for paplay/parecord

**CRITICAL: This plan follows strict TDD methodology per [AGENTS.md](../AGENTS.md)**

## Context

The [`PulseAudioPipeManager`](../amodem_duplex/debugtools/pulseaudio_pipe.py) creates virtual pipes using `module-null-sink` + `module-remap-source`. However, user reports that these pipes don't work with `paplay`/`parecord` and don't appear as actual microphone/speaker devices in browsers or system audio settings.

**Current implementation:**

- Creates null sink (virtual output device)
- Creates remap source that monitors the null sink (records what's played to it)
- Uses `pactl load-module` commands

**Problem:**

- Pipes may not appear as recordable/playable devices
- May not show up in browser audio device lists
- May not work with `paplay`/`parecord` commands
- Could be using wrong PulseAudio module types

**Root cause hypothesis:**

The current module combination (`module-null-sink` + `module-remap-source`) creates a loopback internally, but may not expose proper input/output devices that external applications can use. We may need:

- Different module types (`module-virtual-sink`, `module-virtual-source`)
- Additional `module-loopback` to connect them
- Different property settings to make devices visible to browsers/apps

## The Problem

We need to:

1. **Verify current behavior** - Create a debugging test that checks if pipes work with `paplay`/`parecord`
2. **Diagnose the issue** - Determine why pipes don't appear as usable audio devices
3. **Research solution** - Find correct PulseAudio module configuration for virtual mic/speaker pairs
4. **Fix implementation** - Update [`PulseAudioPipeManager`](../amodem_duplex/debugtools/pulseaudio_pipe.py) to create properly working pipes
5. **Validate fix** - Ensure pipes work with `paplay`, `parecord`, and appear in browser device lists

## The Solution

Add a standalone debugging test in [`amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py`](../amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py) that:

1. **Creates or reuses pipe** - Check if `debug-manual` pipe exists, only create if missing
2. **Verifies device visibility** - Checks that sink/source appear in `pactl list sinks/sources short`
3. **Tests paplay/parecord** - Attempts to use devices with actual audio commands
4. **Enables iterative debugging** - Can be stopped/restarted without recreating pipes

**Use findings to fix the implementation** - Based on what fails, update the module creation logic in [`pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py).

## Implementation Plan

**⚠️ CRITICAL TDD REQUIREMENT (per AGENTS.md):**

1. **Write debugging test FIRST** to diagnose the problem
2. **Run test and capture failures** - Document exactly what doesn't work
3. **Research solution** based on failure modes
4. **Fix implementation** to address root cause
5. **Re-run test** until it passes
6. **Validate manually** with browser/pavucontrol/actual audio tools

### Phase 1: Add Standalone Debugging Test

**File:** [`amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py`](../amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py)

**Add new test method at END of `TestPulseAudioPipeManager` class:**

```python
def test_pipe_works_with_paplay_parecord(self):
    """Standalone debugging test - creates persistent pipe for manual testing."""
    import tempfile
    import time

    manager = pulseaudio_pipe.PulseAudioPipeManager()
    pipe_name = "debug-manual"

    existing_pipe = manager.get(pipe_name)
    if existing_pipe:
        pipe = existing_pipe
        print(f"\n✓ Reusing existing pipe: {pipe.sink_name} / {pipe.source_name}")
    else:
        pipe = manager.create(pipe_name, sample_rate=16000, channels=1)
        print(f"\n✓ Created new pipe: {pipe.sink_name} / {pipe.source_name}")

    # Verify sink exists
    result = subprocess.run(
        ["pactl", "list", "sinks", "short"],
        capture_output=True,
        text=True,
    )
    assert pipe.sink_name in result.stdout, f"Sink {pipe.sink_name} not found in pactl list sinks"
    print(f"✓ Sink visible in pactl list sinks short")

    # Verify source exists
    result = subprocess.run(
        ["pactl", "list", "sources", "short"],
        capture_output=True,
        text=True,
    )
    assert pipe.source_name in result.stdout, f"Source {pipe.source_name} not found in pactl list sources"
    print(f"✓ Source visible in pactl list sources short")

    # Test paplay (play 1 second of silence to sink)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        # Generate 1 second of silence as WAV
        subprocess.run(
            [
                "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", "1", "-f", "wav", tmp.name
            ],
            check=True,
            capture_output=True,
        )

        # Play to our sink
        try:
            subprocess.run(
                ["paplay", "--device", pipe.sink_name, tmp.name],
                check=True,
                capture_output=True,
                timeout=5,
            )
            print(f"✓ paplay successfully played to {pipe.sink_name}")
        except subprocess.TimeoutExpired:
            pytest.fail(f"paplay timed out playing to {pipe.sink_name}")
        except subprocess.CalledProcessError as e:
            pytest.fail(f"paplay failed: {e.stderr.decode()}")

    # Test parecord (record 1 second from source)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        try:
            subprocess.run(
                [
                    "parecord", "--device", pipe.source_name,
                    "--rate", "16000", "--channels", "1",
                    "--format", "s16le", tmp.name
                ],
                check=True,
                capture_output=True,
                timeout=2,
            )
            print(f"✓ parecord successfully recorded from {pipe.source_name}")
        except subprocess.TimeoutExpired:
            # This is actually success - parecord runs until killed
            print(f"✓ parecord connected to {pipe.source_name} (killed after timeout)")
        except subprocess.CalledProcessError as e:
            pytest.fail(f"parecord failed: {e.stderr.decode()}")

    print(f"\n✓ All checks passed!")
    print(f"\nPipe kept for manual testing:")
    print(f"  Sink:   {pipe.sink_name}")
    print(f"  Source: {pipe.source_name}")
    print(f"\nTo delete: aduplex pa delete {pipe_name}")
```

**Key features:**

- **No fixtures** - Creates default manager directly
- **Persistent pipe** - Reuses `debug-manual` pipe if exists (for debugging)
- **Progressive validation** - Checks pactl visibility, then paplay, then parecord
- **Clear output** - Prints what's happening for debugging
- **Keeps pipe** - Doesn't auto-delete so you can inspect/test manually

**Run test:**

```bash
uv run pytest amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py::TestPulseAudioPipeManager::test_pipe_works_with_paplay_parecord -v -s
```

**Expected:** May fail at sink/source visibility OR at paplay/parecord step.

### Phase 2: Capture and Analyze Failure

**Run the test and document:**

1. **Which assertion fails first?**

   - Sink not in `pactl list sinks short`?
   - Source not in `pactl list sources short`?
   - `paplay` can't find device?
   - `parecord` can't find device?

2. **Inspect actual PulseAudio state:**

```bash
# List all sinks
pactl list sinks short

# List all sources
pactl list sources short

# List all modules (look for our sink/source)
pactl list modules short | grep amodem

# Detailed info on our sink
pactl list sinks | grep -A 20 amodem-test-debug-manual

# Detailed info on our source
pactl list sources | grep -A 20 amodem-test-debug-manual
```

3. **Try manual commands:**

```bash
# Try paplay
paplay --device amodem-test-debug-manual-speaker /usr/share/sounds/alsa/Front_Center.wav

# Try parecord
parecord --device amodem-test-debug-manual-mic test.wav
```

4. **Check device properties:**

```bash
# What properties does our sink have?
pactl list sinks | grep -A 50 amodem-test-debug-manual-speaker

# Compare with working sink
pactl list sinks | grep -A 50 "your_real_speaker_name"
```

**Document findings:**

- What module types are created? (null-sink, remap-source)
- What properties are set?
- What's different from a real/working audio device?
- What error messages do paplay/parecord give?

### Phase 3: Research PulseAudio Module Requirements

Based on Phase 2 findings, research:

**Option 1: Current approach is correct, just needs properties**

- Check if `device.class` property needed
- Check if `device.icon_name` needed
- Check if we need to set device as "hardware" vs "virtual"

**Option 2: Need different module types**

Research alternatives:

- `module-virtual-sink` / `module-virtual-source` instead?
- `module-loopback` to connect sink monitoring to source?
- Combination approach (null-sink + loopback → virtual source)?

**Option 3: Need to expose monitor as actual source**

- Current `module-remap-source` monitors the sink
- But maybe browsers/apps need a "real" source, not a monitor?
- May need `module-loopback` to route monitor → new virtual source

**Research resources:**

- PulseAudio module documentation
- Check `pavucontrol` to see how devices are categorized
- Look at how virtual audio cables (VAC) are implemented on Linux
- Check if PipeWire compatibility layer affects this

### Phase 4: Implement Fix in PulseAudioPipeManager

Based on research findings, update [`pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py):

**Potential Fix 1: Add device properties**

Update `_create_null_sink` and `_create_remap_source` to add:

```python
f"sink_properties=device.description={sink_name},device.class=sound"
```

**Potential Fix 2: Use module-loopback**

Add third module to create actual loopback:

```python
def _create_loopback(self, source_name: str, sink_name: str) -> int:
    """Create loopback from sink monitor to source."""
    args = [
        "pactl", "load-module", "module-loopback",
        f"source={sink_name}.monitor",
        f"sink={source_name}",
        "latency_msec=1",
    ]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return int(result.stdout.strip())
```

Then update `create()` to use it and store loopback module ID in `PulseAudioPipe` dataclass.

**Potential Fix 3: Different module combination**

Replace remap-source with something else based on research.

**Update dataclass if needed:**

```python
@dataclasses.dataclass
class PulseAudioPipe:
    id: str
    name: str
    sink_name: str
    source_name: str
    sink_module_id: int | None
    source_module_id: int | None
    loopback_module_id: int | None  # If adding loopback
    sample_rate: int
    channels: int
```

**Update deletion logic** to unload all modules (including loopback if added).

### Phase 5: Validate Fix with Debugging Test

**Re-run the test:**

```bash
uv run pytest amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py::TestPulseAudioPipeManager::test_pipe_works_with_paplay_parecord -v -s
```

**Expected:** Should progress further or pass completely.

**If still failing:**

- Go back to Phase 2/3, refine understanding
- Try different module configurations
- Check PulseAudio/PipeWire compatibility layers

**Iterate until test passes.**

### Phase 6: Manual Validation

Once test passes, validate manually:

**6.1 Test with browser:**

- Open browser (Firefox/Chrome)
- Go to a site that uses microphone (e.g., https://www.onlinemictest.com/)
- Check if `amodem-test-debug-manual-mic` appears in microphone list
- Check if `amodem-test-debug-manual-speaker` appears in speaker list

**6.2 Test with pavucontrol:**

```bash
pavucontrol
```

- Check "Output Devices" tab - should see our sink
- Check "Input Devices" tab - should see our source
- Verify they show as available devices

**6.3 Test roundtrip with actual audio:**

```bash
# Play audio file to sink while recording from source
parecord --device amodem-test-debug-manual-mic output.wav &
RECORD_PID=$!
sleep 1
paplay --device amodem-test-debug-manual-speaker /usr/share/sounds/alsa/Front_Center.wav
sleep 2
kill $RECORD_PID

# Play back recorded audio to verify roundtrip worked
paplay output.wav
```

**6.4 Test with amodem_duplex encoder/decoder:**

Create simple script to test actual encoding/decoding through the pipe (similar to plan007 integration tests but simpler).

### Phase 7: Update Existing Tests

**Update all existing tests in [`test_pulseaudio_pipe.py`](../amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py):**

If dataclass or method signatures changed (e.g., added loopback_module_id), update:

- Assertions in `test_create_pipe_returns_pipe_with_module_ids`
- Cleanup logic in `test_delete_pipe_removes_devices`
- Any other tests that check module IDs or pipe structure

**Run full test suite:**

```bash
uv run pytest amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py -v
```

**Expected:** All tests pass, including new debugging test.

### Phase 8: Code Quality and Cleanup

**8.1 Format code:**

```bash
uv run black amodem_duplex/debugtools/pulseaudio_pipe.py
uv run black amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py
```

**8.2 Check linting:**

```bash
uv run ruff check amodem_duplex/debugtools/pulseaudio_pipe.py
uv run ruff check amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py
```

**Fix any issues.**

**8.3 Run full amodem_duplex test suite:**

```bash
uv run pytest amodem_duplex/ -v
```

**Verify:** No regressions in other tests.

**8.4 Clean up debug pipe:**

```bash
uv run python -m amodem_duplex.debugtools pa delete debug-manual
```

Or keep it for future debugging.

### Phase 9: Write Comprehensive Report

Create [`reports/report008.md`](../reports/report008.md) documenting:

1. **Objective** - Fix PulseAudio pipes to work with paplay/parecord and browsers
2. **Problem Statement** - What wasn't working, symptoms
3. **Root Cause Analysis** - What was wrong with module configuration
4. **Solution** - What changes were made and why
5. **Files Modified**:
   - [`amodem_duplex/debugtools/pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py) - Implementation fix
   - [`amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py`](../amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py) - Added debugging test
6. **Technical Details**:
   - PulseAudio module types used
   - Properties required for device visibility
   - How loopback works (if added)
   - Why previous approach didn't work
7. **Test Results**:
   - Debugging test output (before and after fix)
   - Manual validation results (browser, pavucontrol, paplay/parecord)
   - Full test suite results
8. **Validation**:
   - Devices visible in `pactl list`
   - `paplay`/`parecord` work correctly
   - Devices appear in browser audio settings
   - Devices appear in pavucontrol
9. **Success Criteria** - All met
10. **Future Considerations** - Any limitations or edge cases

**Follow the structure of existing reports:**

- [`reports/report006.md`](../reports/report006.md) - Similar troubleshooting/fix approach
- [`reports/report007.md`](../reports/report007.md) - Integration testing pattern

## Design Considerations

### Test Design: Standalone Debugging Test

**Decision: Create persistent pipe for iterative debugging**

**Rationale:**

- Allows stopping test mid-run to inspect PulseAudio state
- Can reuse pipe across test runs (faster iteration)
- Can manually test with browser/pavucontrol without recreating
- Mimics real debugging workflow

**Alternative considered:**

- Use fixture-based test that auto-cleans up
- Problem: Can't inspect state after test, must recreate each time

### Module Architecture: Three-Module Approach (Hypothesis)

**Decision: May need null-sink + remap-source + loopback**

**Rationale (to be validated):**

- `module-null-sink`: Creates virtual output (speaker)
- `module-remap-source`: Creates monitor of sink (captures what's played)
- `module-loopback`: Routes monitor → virtual input (mic)

This three-step approach may be needed because:

- Monitors aren't recordable by default
- Need explicit loopback to make monitor data available as input
- Browser/apps may not see monitors as "real" microphones

**Alternative considered:**

- Two-module approach (current implementation)
- May work with just property changes
- Need to validate which approach is correct

### Validation Strategy: Progressive Checks

**Decision: Check pactl visibility before paplay/parecord**

**Rationale:**

- If devices don't appear in `pactl list`, they definitely won't work with apps
- Progressive validation identifies failure point quickly
- Clearer error messages for debugging

**Validation layers:**

1. Device appears in `pactl list sinks/sources short`
2. `paplay` can play to device
3. `parecord` can record from device
4. Browser can see and use device
5. pavucontrol shows device

### Scope: Fix, Don't Redesign

**Decision: Minimal changes to make pipes work**

**Rationale:**

- Goal is to fix existing `PulseAudioPipeManager`
- Don't redesign entire architecture
- Just fix module configuration to work correctly

**NOT in scope:**

- Advanced features (multiple loopbacks, routing matrices, etc.)
- Performance optimization
- Cross-platform support (Windows/macOS)
- PipeWire-native implementation

## Files to Modify

1. **[`amodem_duplex/debugtools/pulseaudio_pipe.py`](../amodem_duplex/debugtools/pulseaudio_pipe.py)** - Fix module creation logic
2. **[`amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py`](../amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py)** - Add debugging test

## Files to Create (Report)

1. **[`reports/report008.md`](../reports/report008.md)** - Comprehensive troubleshooting and fix report

## Key Design Decisions

1. **Standalone debugging test** - Persistent pipe for iterative testing
2. **Progressive validation** - Check pactl → paplay → parecord → browser
3. **Research-driven fix** - Diagnose first, then fix based on findings
4. **Minimal changes** - Fix what's broken, don't redesign
5. **Manual validation** - Test with real browser and pavucontrol
6. **Keep debug pipe** - Don't auto-delete for manual inspection
7. **TDD approach** - Test reveals problem, then fix it
8. **Actually test with audio** - Not just mocks or assertions

## Alignment with AGENTS.md

- ✅ **Keep it simple** - One debugging test, minimal fix
- ✅ **Don't over-engineer** - Fix module config, don't redesign
- ✅ **Stay focused** - Just make paplay/parecord work
- ✅ **TDD methodology** - Test first to diagnose problem
- ✅ **Actually run tests** - Explicit validation at each phase
- ✅ **Read context first** - Plan references existing implementation
- ✅ **Use uv run** - All commands use `uv run`
- ✅ **Type annotations** - Update dataclass if needed
- ✅ **Logging** - Use LOGGER for module creation/deletion
- ✅ **Format with black** - Explicit validation step
- ✅ **Check with ruff** - Explicit validation step
- ✅ **Write comprehensive report** - Following existing report style

## Success Criteria

- ✅ Debugging test added to `test_pulseaudio_pipe.py`
- ✅ Test initially fails, revealing problem
- ✅ Root cause identified through test failures and manual inspection
- ✅ `PulseAudioPipeManager` implementation fixed
- ✅ Debugging test passes after fix
- ✅ Devices visible in `pactl list sinks/sources short`
- ✅ `paplay` works with sink
- ✅ `parecord` works with source
- ✅ Devices appear in browser audio device list
- ✅ Devices appear in pavucontrol
- ✅ No regressions in existing test suite
- ✅ No linter errors (black, ruff)
- ✅ Comprehensive report written in `reports/report008.md`

## Expected Outcome

After implementation, `amodem_duplex` will have:

- **Working virtual audio pipes** - Appear as real mic/speaker devices
- **Browser compatibility** - Devices selectable in web audio APIs
- **CLI tool support** - Work with `paplay`, `parecord`, `ffmpeg`, etc.
- **Debugging infrastructure** - Standalone test for troubleshooting
- **Validated solution** - Tested with real applications, not just unit tests

**Testing strategy:**

- **Debugging test** - Validates paplay/parecord work
- **Manual validation** - Browser, pavucontrol, actual audio roundtrip
- **Existing tests** - Ensure no regressions in pipe creation/deletion

**Known limitations:**

- Requires PulseAudio or PipeWire with PulseAudio compatibility
- Virtual devices only (not physical hardware)
- May have latency (acceptable for testing/debugging use case)
