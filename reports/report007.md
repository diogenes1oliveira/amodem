# Report 007: Fixed PulseAudio Pipes with Loopback for Real Audio Roundtrip

**Date:** 2025-11-29  
**Status:** Complete  
**Related Plan:** [plan007.md](../plans/plan007.md)

## Objective

Fix PulseAudio virtual pipes to enable **real bidirectional audio routing** that works with `paplay`, `parecord`, and browser audio devices. The existing implementation created devices that appeared in `pactl list` but audio played to the sink didn't actually route to the source for recording.

## Summary

Successfully implemented a **three-module PulseAudio pipe architecture** (null-sink + loopback + remap-source) that creates truly functional bidirectional audio pipes. Audio played via `paplay` to the virtual speaker now successfully routes through the virtual microphone and can be captured via `parecord`.

### Key Achievement

**Real audio roundtrip validated with sine wave analysis:**

- Generated 1kHz sine wave at 16000 Hz sample rate
- Played via `paplay` to virtual speaker
- Recorded via `parecord` from virtual microphone
- Verified RMS ~20290 (strong signal, not silence)
- All 9 tests pass (8 existing + 1 new roundtrip test)

### Test Results

- **9 tests** - all passing against real PulseAudio
- **Full roundtrip test** - paplay → speaker → mic → parecord works with real audio
- **RMS validation** - Recorded audio has strong signal (>1000), confirming audio routing
- **0 failures**
- **0 linter errors** (ruff and black)

## The Problem

### Original Implementation (Two Modules)

The original PulseAudio pipe used only two modules:

1. **module-null-sink** - Creates virtual speaker (sink)
2. **module-remap-source** - Monitors the null-sink

**Critical flaw:** The remap-source monitors the sink's `.monitor` output, but this monitor is **passive**. Without an active consumer, audio written to the null-sink has nowhere to go, causing tools like `paplay` to hang waiting for the sink to accept audio.

### Symptoms

- `paplay` would **timeout/hang** when writing to the virtual speaker
- Even when it didn't hang, audio wasn't routed to the virtual microphone
- Devices appeared in `pactl list` but weren't functionally connected
- No actual audio roundtrip possible

### Root Cause

**Null sinks block on write until there's an active reader.** The monitor source doesn't count as an active reader - it just passively captures what's played. Without something actively reading from the monitor, the sink blocks indefinitely.

## The Solution

### Three-Module Architecture

Added **module-loopback** to create an active audio routing path:

1. **module-null-sink** (speaker) - Accepts audio via paplay
2. **module-loopback** - Actively routes `null-sink.monitor` → default sink
3. **module-remap-source** (mic) - Captures from `null-sink.monitor` via parecord

**Key insight:** The loopback module creates an **active consumer** of the null-sink's monitor, which:

- Unblocks the null sink so `paplay` can write audio
- Routes audio to the default sink (making it audible if desired)
- Makes the monitor data available for the remap-source to capture

### Architecture Diagram

```
paplay → [null-sink (speaker)]
                ↓ .monitor
                ├→ [loopback] → default sink (audible)
                └→ [remap-source (mic)] → parecord
```

### Implementation Details

**Module creation sequence in `create()` method:**

```python
# 1. Create null sink (virtual speaker)
sink_module_id = self._create_null_sink(sink_name, sample_rate, channels)

# 2. Create loopback to unblock sink and route audio
loopback_module_id = self._create_loopback(f"{sink_name}.monitor", sample_rate, channels)

# 3. Create remap source (virtual microphone)
source_module_id = self._create_remap_source(source_name, f"{sink_name}.monitor")
```

**New loopback module method:**

```python
def _create_loopback(self, source: str, sample_rate: int, channels: int) -> int:
    """Create loopback module to route audio from source to default sink."""
    args = [
        "pactl", "load-module", "module-loopback",
        f"source={source}",
        f"rate={sample_rate}",
        f"channels={channels}",
        "latency_msec=1",
    ]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return int(result.stdout.strip())
```

**Deletion includes all three modules:**

```python
def delete(self, identifier: str) -> bool:
    sink_module_id = self._find_module_id_for_sink(pipe.sink_name)
    source_module_id = self._find_module_id_for_source(pipe.source_name)
    loopback_module_id = self._find_loopback_module_id(f"{pipe.sink_name}.monitor")

    sink_ok = self._unload_module(sink_module_id)
    source_ok = self._unload_module(source_module_id)
    loopback_ok = self._unload_module(loopback_module_id)

    return sink_ok or source_ok or loopback_ok
```

## Files Modified

### 1. `amodem_duplex/debugtools/pulseaudio_pipe.py`

**Changes:**

- **Updated `PulseAudioPipe` dataclass** - Added `loopback_module_id: int | None` field
- **Added `_create_loopback()` method** - Creates module-loopback instance
- **Added `_find_loopback_module_id()` method** - Finds loopback module for deletion
- **Updated `create()` method** - Creates loopback between sink and source
- **Updated `delete()` method** - Deletes all three modules (sink, loopback, source)
- **Updated `list_all()` return** - Includes `loopback_module_id=None` in pipe objects
- **Enhanced `_create_null_sink()`** - Added `channel_map` and `format=s16le` parameters
- **Enhanced logging** - Now logs all three module IDs

**Lines changed:** ~60 lines added/modified (new methods, updated signatures, enhanced module creation)

### 2. `amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py`

**Changes:**

- **Added `test_pipe_works_with_paplay_parecord()` method** - Full roundtrip test
  - Generates 1kHz sine wave using numpy
  - Writes to temp file for paplay
  - Starts parecord in background
  - Plays audio via paplay
  - Stops recording after capture
  - Verifies recorded RMS > 1000 (strong signal)
  - Cleans up temp files

**Lines added:** ~135 lines (new comprehensive test)

## Technical Implementation

### PulseAudio Module Commands

**Creating the pipe (3 commands):**

```bash
# 1. Create null sink (speaker)
pactl load-module module-null-sink \
  sink_name=amodem-test-pytest-patest-speaker \
  sink_properties=device.description=amodem-test-pytest-patest-speaker \
  rate=16000 \
  channels=1 \
  channel_map=mono \
  format=s16le
# Returns: module ID 352

# 2. Create loopback (routes monitor to default sink)
pactl load-module module-loopback \
  source=amodem-test-pytest-patest-speaker.monitor \
  rate=16000 \
  channels=1 \
  latency_msec=1
# Returns: module ID 353

# 3. Create remap source (mic)
pactl load-module module-remap-source \
  source_name=amodem-test-pytest-patest-mic \
  master=amodem-test-pytest-patest-speaker.monitor \
  source_properties=device.description=amodem-test-pytest-patest-mic
# Returns: module ID 354
```

**Deleting the pipe (3 commands):**

```bash
pactl unload-module 352  # null sink
pactl unload-module 353  # loopback
pactl unload-module 354  # remap source
```

### Finding Loopback Module ID

**Challenge:** Need to find loopback module ID when deleting, but we only know the source name.

**Solution:** Parse `pactl list modules short` and match on source parameter:

```python
def _find_loopback_module_id(self, source: str) -> int | None:
    result = subprocess.run(
        ["pactl", "list", "modules", "short"],
        check=True, capture_output=True, text=True,
    )
    for line in result.stdout.strip().split("\n"):
        if "module-loopback" in line and f"source={source}" in line:
            parts = line.split()
            if parts:
                return int(parts[0])
    return None
```

### Audio Format Enhancements

Added explicit audio format parameters to null-sink creation:

- **channel_map** - "mono" for 1 channel, "stereo" for 2 channels
- **format** - "s16le" (16-bit signed little-endian PCM)

This ensures consistent format across the entire audio pipeline.

## New Test: Full Roundtrip Validation

### Test Design

The `test_pipe_works_with_paplay_parecord()` test validates the complete audio path:

1. **Setup** - Create pipe with manager fixture
2. **Verify visibility** - Check sink/source appear in `pactl list`
3. **Generate audio** - Create 1kHz sine wave with numpy
4. **Record setup** - Start parecord in background subprocess
5. **Playback** - Play sine wave via paplay to virtual speaker
6. **Capture** - Stop recording, read captured audio file
7. **Validate** - Calculate RMS, verify strong signal (>1000)

### Sine Wave Generation

```python
sample_rate = 16000
duration = 1.0
frequency = 1000.0
t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
sine_wave = np.sin(2 * np.pi * frequency * t)
audio_data = (sine_wave * 32767).astype(np.int16).tobytes()
```

**Why 1kHz sine wave:**

- Easy to generate with numpy
- Clear, predictable signal
- High RMS when played at full volume
- Easy to verify vs silence

### RMS Validation

```python
recorded_samples = np.frombuffer(recorded_bytes, dtype=np.int16)
rms = np.sqrt(np.mean(recorded_samples.astype(np.float32) ** 2))
assert rms > 1000, f"RMS too low ({rms:.2f}), likely silence or weak signal"
```

**Expected RMS for 1kHz sine at full volume:** ~20000-23000  
**Actual RMS measured:** ~20290 ✅

This confirms real audio is being routed, not silence or noise.

### Test Output

```
✓ Sink visible in pactl list sinks short
✓ Source visible in pactl list sources short
✓ paplay successfully played to amodem-test-pytest-patest-speaker
✓ parecord successfully recorded from amodem-test-pytest-patest-mic
✓ Recorded 41618 bytes of audio data
✓ Recorded RMS: 20290.99
✓ Audio contains real signal (RMS > 1000)

✓ Full roundtrip test passed!
```

## TDD Methodology (Per AGENTS.md)

Followed strict TDD as required by the plan:

### Phase 1: Test First

- Created `test_pipe_works_with_paplay_parecord()` skeleton
- Initial test failed with timeout on paplay (as expected)

### Phase 2: Diagnose Problem

- Observed paplay hanging when writing to null-sink
- Researched PulseAudio documentation
- Discovered null sinks block until there's an active reader
- Found that loopback modules create active readers

### Phase 3: Implement Fix

- Added `_create_loopback()` method
- Updated `create()` to instantiate loopback module
- Added `loopback_module_id` to dataclass
- Updated deletion logic to remove loopback

### Phase 4: Validate Fix

- Test now passes with full roundtrip
- RMS validation confirms real audio routing
- All existing tests still pass (no regressions)

### Phase 5: Code Quality

- Formatted with black (2 files reformatted)
- Fixed ruff warnings (bare except → OSError)
- Final: 0 linter errors

## Challenges Encountered

### 1. paplay Timeout Mystery

**Problem:** Initial test showed paplay timing out after 2 seconds when writing to newly created pipes, but an old manually-created pipe worked fine.

**Investigation:**

- Tried adding delays before paplay
- Tried starting parecord before paplay
- Tried adding PulseAudio module parameters (channel_map, format)
- All attempts still resulted in timeout

**Solution:** Research revealed that null sinks need an **active consumer** to accept data. The old pipe worked because it had been used previously and had accumulated PulseAudio state. The solution was adding module-loopback to create an active consumer.

### 2. Finding the Right Module Combination

**Problem:** PulseAudio documentation describes many module types. Which combination creates a working bidirectional pipe?

**Research approach:**

- Read PulseAudio module documentation (module-null-sink, module-loopback, module-remap-source)
- Studied working examples of virtual audio cables on Linux
- Analyzed the difference between passive monitoring vs active routing

**Discovery:** Three-module approach is standard for virtual audio cables:

1. Null-sink creates the virtual device
2. Loopback routes audio (creates active consumer)
3. Remap-source makes monitor available as source

### 3. Module ID Tracking

**Problem:** Need to delete loopback module but don't store its ID persistently.

**Solution:** Query `pactl list modules short` and match by source name:

```bash
pactl list modules short | grep "module-loopback.*source=amodem-test-pytest-patest-speaker.monitor"
```

This finds the loopback module dynamically during deletion.

## Validation

### Automated Testing

```bash
$ uv run pytest amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py -xvs

test_create_pipe_creates_real_devices PASSED
test_create_pipe_returns_pipe_with_module_ids PASSED
test_delete_pipe_removes_devices PASSED
test_list_all_returns_created_pipes PASSED
test_get_finds_pipe_by_name PASSED
test_delete_all_removes_all_matching_pipes PASSED
test_pactl_not_available_raises_error PASSED
test_created_devices_visible_in_pactl_list PASSED
test_pipe_works_with_paplay_parecord PASSED

=================================================================== 9 passed in 3.92s ===================================================================
```

### Manual Testing

**Verified devices appear in pactl:**

```bash
$ pactl list sinks short | grep amodem-test
382	amodem-test-pytest-patest-speaker	module-null-sink.c	s16le 1ch 16000Hz	RUNNING

$ pactl list sources short | grep amodem-test
384	amodem-test-pytest-patest-mic	module-remap-source.c	s16le 1ch 16000Hz	IDLE
```

**Verified modules created:**

```bash
$ pactl list modules short | grep amodem-test
352	module-null-sink	sink_name=amodem-test-pytest-patest-speaker ...
353	module-loopback	source=amodem-test-pytest-patest-speaker.monitor ...
354	module-remap-source	source_name=amodem-test-pytest-patest-mic ...
```

### Code Quality

```bash
$ uv run black amodem_duplex/debugtools/pulseaudio_pipe.py amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py
reformatted amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py
reformatted amodem_duplex/debugtools/pulseaudio_pipe.py
All done! ✨ 🍰 ✨

$ uv run ruff check amodem_duplex/debugtools/pulseaudio_pipe.py amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py
All checks passed!
```

## Success Criteria (All Met)

From [plan007.md](../plans/plan007.md):

1. ✅ Debugging test added to `test_pulseaudio_pipe.py`
2. ✅ Test initially failed (paplay timeout), revealing problem
3. ✅ Root cause identified (null-sink needs active consumer)
4. ✅ `PulseAudioPipeManager` implementation fixed (added loopback)
5. ✅ Debugging test passes after fix
6. ✅ Devices visible in `pactl list sinks/sources short`
7. ✅ `paplay` works with sink (no timeout)
8. ✅ `parecord` works with source (captures real audio)
9. ✅ Real audio roundtrip validated (RMS ~20290)
10. ✅ No regressions in existing test suite (8 tests still pass)
11. ✅ No linter errors (black, ruff)
12. ✅ Comprehensive report written

## Alignment with AGENTS.md

1. **Keep it simple** ✅ - Added one module (loopback), minimal change
2. **Don't over-engineer** ✅ - Standard three-module PulseAudio pattern
3. **Stay focused** ✅ - Fixed audio routing, nothing more
4. **TDD strict** ✅ - Test revealed problem, guided solution
5. **Actually run tests** ✅ - All tests executed, output validated
6. **Type annotations** ✅ - Added `loopback_module_id: int | None`
7. **Format with black** ✅ - Both files formatted
8. **Use ruff** ✅ - All warnings fixed
9. **Logging** ✅ - LOGGER logs all three module IDs

## Lessons Learned

### 1. Null Sinks Need Active Consumers

**Key insight:** PulseAudio null sinks **block on write** until there's an active consumer. A monitor source is passive - it doesn't consume, it just observes. This is why paplay hung.

**Solution:** module-loopback creates an active consumer by routing the monitor to the default sink.

### 2. Don't Trust Device Visibility Alone

The original implementation created devices that appeared in `pactl list`, leading to the assumption they worked. But appearance in the device list doesn't mean the audio path is functional.

**Lesson:** Always test with **real audio roundtrip**, not just device enumeration.

### 3. PulseAudio Documentation Has the Answers

The PulseAudio wiki documentation on modules clearly explains:

- module-null-sink creates virtual devices
- module-loopback routes audio between sources and sinks
- module-remap-source creates a source from a monitor

Reading the documentation carefully would have revealed the solution faster.

### 4. RMS Validation is Powerful

Simply checking "did we record bytes?" isn't enough. The RMS calculation proves:

- Audio is not silence (RMS > 0)
- Audio has strong signal (RMS > 1000)
- Audio is at expected level (RMS ~20290 for full-volume sine)

This single metric validates the entire audio pipeline.

## Future Considerations

### Potential Enhancements (Not Needed Now)

1. **Configurable loopback routing** - Allow routing to specific sink instead of default
2. **Latency tuning** - Make `latency_msec` configurable
3. **Multi-channel support** - Test stereo/surround configurations
4. **Browser compatibility** - Verify virtual devices appear in web audio API
5. **Performance monitoring** - Track CPU usage of loopback module

### Known Limitations

1. **Requires PulseAudio** - Won't work on pure ALSA systems
2. **Latency overhead** - Loopback adds ~1ms latency (acceptable for testing)
3. **CPU overhead** - Three modules per pipe (minimal impact)
4. **Audio quality** - Resampling in loopback could affect quality (negligible at 16kHz)

## Comparison: Before vs After

| Aspect                    | Before (2 modules)      | After (3 modules)      |
| ------------------------- | ----------------------- | ---------------------- |
| **Modules**               | null-sink, remap-source | + loopback             |
| **paplay behavior**       | Timeout/hang            | Works ✅               |
| **parecord behavior**     | Connects but no audio   | Captures real audio ✅ |
| **Audio roundtrip**       | Not possible            | Fully functional ✅    |
| **RMS validation**        | N/A                     | ~20290 (strong) ✅     |
| **Browser compatibility** | Unknown                 | Ready to test          |
| **Tests**                 | 8 (no roundtrip test)   | 9 (with roundtrip) ✅  |

## Conclusion

Successfully fixed PulseAudio virtual pipes by adding **module-loopback** to create an active audio routing path. The three-module architecture (null-sink + loopback + remap-source) is the standard approach for virtual audio cables in PulseAudio.

The implementation is production-ready:

- ✅ **Full audio roundtrip** - paplay → speaker → mic → parecord works
- ✅ **Real audio validated** - RMS ~20290 confirms strong signal
- ✅ **All 9 tests pass** - Including new comprehensive roundtrip test
- ✅ **Zero linter errors** - black and ruff checks pass
- ✅ **Strict TDD methodology** - Test revealed problem, guided solution
- ✅ **No regressions** - All existing tests still pass

The PulseAudio virtual pipes are now ready for:

- Testing audio modem applications
- Browser audio API integration
- Full-duplex audio streaming validation
- Real-world debugging scenarios

**Test Count:**

- Before: 8 tests
- After: 9 tests (8 existing + 1 new roundtrip)
- All passing ✅
