# Integration Tests with Real PulseAudio Pipes

**CRITICAL: This plan follows strict TDD methodology per [AGENTS.md](../AGENTS.md)**

## Context

The existing test suite in [`amodem_duplex/tests/`](../amodem_duplex/tests/) uses in-memory loopback tests - encoding PCM chunks and immediately feeding them to the decoder without any real audio I/O. While this provides fast, deterministic testing, it doesn't validate the full stack with real-time audio constraints.

**Current testing approach:**

- PCM flows directly from encoder to decoder (no real audio devices)
- Perfect timing (no latency, no buffering delays)
- Synthetic failures (injected noise/corruption)
- Very fast execution

**Gap:** No tests verify that encoding/decoding actually works through real audio pipes with real-time constraints.

## The Problem

We need **smoke tests** that validate the full audio stack end-to-end:

1. **Real audio I/O** - Actually play PCM to a PulseAudio sink and record from a source
2. **Real-time constraints** - Handle buffering, latency, timing synchronization
3. **PulseAudio integration** - Verify the [`PulseAudioPipeManager`](../amodem_duplex/debugtools/pulseaudio_pipe.py) works in a realistic scenario
4. **Basic validation** - Simple smoke tests, not comprehensive scenarios (already covered in [`test_loopback.py`](../amodem_duplex/tests/test_loopback.py))

**Key constraints:**

- Can't use fake monotonic clock (real I/O has real timing)
- Must handle audio stream synchronization
- Tests will be slower (real-time audio playback/recording)
- Requires PulseAudio to be available on the system

## The Solution

Create integration tests in [`amodem_duplex/tests/test_pulseaudio_integration.py`](../amodem_duplex/tests/test_pulseaudio_integration.py) that:

1. Use real PulseAudio virtual pipes (via [`PulseAudioPipeManager`](../amodem_duplex/debugtools/pulseaudio_pipe.py))
2. Use `sounddevice` library for actual audio I/O
3. Stream PCM chunks to the pipe's sink (output device)
4. Record PCM chunks from the pipe's source (input device)
5. Verify packets decode correctly
6. Keep tests minimal - just smoke tests for basic validation

## Implementation Plan

**⚠️ CRITICAL TDD REQUIREMENT (per AGENTS.md):**

1. **ALWAYS write tests FIRST**
2. **Tests should fail initially** (red) - may need skeleton implementation
3. **Then implement to make them pass** (green)
4. **Actually run tests** - don't just say "ready for testing"
5. **Follow this order strictly**: Test skeleton → Test implementation → Run test → Fix failures → Validate

### Phase 1: Create Test Skeleton FIRST

**File:** [`amodem_duplex/tests/test_pulseaudio_integration.py`](../amodem_duplex/tests/test_pulseaudio_integration.py)

Create test file with:

- Header: `# mypy: disable-error-code="no-untyped-def"`
- Import statements (pytest, numpy, sounddevice, encoder, decoder, PulseAudioPipeManager, etc.)
- Skip marker if `pactl` not available
- Test class: `TestPulseAudioIntegration`
- **All fixtures defined at TOP of class** before test methods
- All test method signatures with single `pass` statement
- NO comments (test names are descriptive)

**Fixtures to define (at top of class):**

```python
@pytest.fixture
def manager(self):
    """Create PulseAudioPipeManager instance with cleanup."""
    pass

@pytest.fixture
def pipe(self, manager):
    """Create a single test pipe."""
    pass

@pytest.fixture
def config(self):
    """Get slowest amodem config for reliable transmission."""
    pass

@pytest.fixture
def enc(self, config):
    """Create StreamEncoder instance."""
    pass

@pytest.fixture
def dec(self, config):
    """Create StreamDecoder instance."""
    pass
```

**Test methods to create:**

- `test_single_packet_roundtrip` - Encode one small packet, decode through real pipe
- `test_multiple_packets_roundtrip` - Encode 3-5 packets sequentially
- `test_interrupted_stream` - Stop transmission mid-stream, verify graceful handling

**Pytest markers:**

```python
import shutil
import pytest

# Skip all tests if pactl not available
pytestmark = [
    pytest.mark.skipif(
        shutil.which("pactl") is None,
        reason="pactl not available (PulseAudio not installed)"
    ),
    pytest.mark.slow,
    pytest.mark.integration,
]
```

**STOP HERE and run:** `uv run pytest amodem_duplex/tests/test_pulseaudio_integration.py -v`

All tests should pass (they just have `pass` statements).

### Phase 2: Implement Fixtures

**CRITICAL: Define all fixtures at the top before test methods**

Implement each fixture:

**2.1 Manager fixture:**

```python
@pytest.fixture
def manager(self):
    mgr = PulseAudioPipeManager(prefix="amodem-pytest-integration")
    yield mgr
    # Cleanup: delete all test pipes
    mgr.delete_all()
```

**2.2 Pipe fixture:**

```python
@pytest.fixture
def pipe(self, manager):
    return manager.create("test-pipe", sample_rate=16000, channels=1)
```

**2.3 Config fixture:**

```python
@pytest.fixture
def config(self):
    return amodem.config.slowest()
```

**2.4 Encoder fixture:**

```python
@pytest.fixture
def enc(self, config):
    # Use default chunk_samples (640 = 40ms @ 16kHz)
    return encoder.StreamEncoder(config, chunk_samples=640)
```

**2.5 Decoder fixture:**

```python
@pytest.fixture
def dec(self, config):
    return decoder.StreamDecoder(config, crc_error_threshold=3)
```

**Run tests:** `uv run pytest amodem_duplex/tests/test_pulseaudio_integration.py -v`

Tests should still pass (just `pass` statements in test methods).

### Phase 3: Implement Helper Method

**Location:** Inside `TestPulseAudioIntegration` class (after fixtures, before test methods)

**Method signature:**

```python
def _encode_decode_through_pipe(
    self,
    enc: encoder.StreamEncoder,
    dec: decoder.StreamDecoder,
    pipe: PulseAudioPipe,
    packets: list[bytes],
) -> list[bytes]:
    """Encode packets, play through real PulseAudio pipe, record and decode."""
    pass  # Skeleton first
```

**Implementation approach:**

1. **Collect all PCM chunks from encoder:**

   - Emit preamble via `enc.emit_preamble()`
   - Feed all packets via `enc.feed_packet()`
   - Extract all PCM chunks via `enc.get_pcm_chunk()`
   - Concatenate into single numpy array

2. **Open audio streams using sounddevice:**

   - Output stream: play to `pipe.sink_name`
   - Input stream: record from `pipe.source_name`
   - Sample rate: 16000 (match encoder config)
   - Channels: 1 (mono)
   - Dtype: float32 or float64 (match encoder PCM)

3. **Synchronization strategy:**

   - Start recording FIRST (with sufficient buffer to avoid missing preamble)
   - Then start playback
   - Use blocking I/O or callbacks (blocking is simpler for tests)

4. **Stream PCM data:**

   - Write PCM chunks to output stream
   - Read PCM chunks from input stream (same chunk size: 640 samples)
   - Feed recorded PCM to decoder via `dec.feed_pcm()`

5. **Extract decoded packets:**
   - Call `dec.get_packet()` in loop
   - Collect until no more packets available
   - Return list of decoded packets

**Key decisions:**

- **Audio library:** Use `sounddevice` (simpler API, native numpy support)
- **Buffering:** Start recording before playback to capture full preamble
- **Chunk size:** Use encoder's chunk_samples (640) for consistency
- **Timing:** Let sounddevice handle real-time timing (no manual delays)

**Implementation sketch:**

```python
def _encode_decode_through_pipe(
    self,
    enc: encoder.StreamEncoder,
    dec: decoder.StreamDecoder,
    pipe: PulseAudioPipe,
    packets: list[bytes],
) -> list[bytes]:
    import sounddevice as sd

    # Collect all PCM from encoder
    all_pcm = list(enc.emit_preamble())
    for pkt in packets:
        enc.feed_packet(pkt)
    while enc.has_data():
        chunk = enc.get_pcm_chunk()
        if chunk is not None:
            all_pcm.append(chunk)

    pcm_data = np.concatenate(all_pcm)

    # Open streams
    # Play to sink, record from source
    # (Implementation details: use sd.OutputStream and sd.InputStream)
    # Stream data through pipe
    # Feed recorded chunks to decoder

    # Extract packets
    decoded = []
    for _ in range(len(packets) + 10):  # Extra attempts
        pkt = dec.get_packet()
        if pkt is not None:
            decoded.append(bytes(pkt))

    return decoded
```

**Note:** Actual sounddevice implementation may use blocking read/write or callbacks. Start simple with blocking I/O.

### Phase 4: Implement Test Methods

**For EACH test method:**

1. **Write test implementation** with setup/act/verify blocks (NO comment labels)
2. **Run the test**: `uv run pytest path/to/test.py::TestClass::test_method -v`
3. **Test should FAIL initially** (if helper not complete)
4. **Fix implementation iteratively**
5. **Re-run until PASS**

**4.1 Test: Single packet roundtrip**

```python
def test_single_packet_roundtrip(
    self,
    enc: encoder.StreamEncoder,
    dec: decoder.StreamDecoder,
    pipe: PulseAudioPipe,
):
    payload = b"Hello, PulseAudio!"

    decoded = self._encode_decode_through_pipe(enc, dec, pipe, [payload])

    assert len(decoded) == 1
    assert decoded[0] == payload
```

**Run:** `uv run pytest amodem_duplex/tests/test_pulseaudio_integration.py::TestPulseAudioIntegration::test_single_packet_roundtrip -v`

**Expected:** May fail if helper not complete. Fix helper, re-run.

**4.2 Test: Multiple packets**

```python
def test_multiple_packets_roundtrip(
    self,
    enc: encoder.StreamEncoder,
    dec: decoder.StreamDecoder,
    pipe: PulseAudioPipe,
):
    packets = [b"Packet 1", b"Packet 2", b"Packet 3", b"Packet 4", b"Packet 5"]

    decoded = self._encode_decode_through_pipe(enc, dec, pipe, packets)

    assert len(decoded) == len(packets)
    assert decoded == packets
```

**Run:** `uv run pytest amodem_duplex/tests/test_pulseaudio_integration.py::TestPulseAudioIntegration::test_multiple_packets_roundtrip -v`

**4.3 Test: Interrupted stream**

```python
def test_interrupted_stream(
    self,
    enc: encoder.StreamEncoder,
    dec: decoder.StreamDecoder,
    pipe: PulseAudioPipe,
):
    # Encode multiple packets but only transmit first 50% of PCM
    packets = [b"Full", b"Transmission", b"Interrupted"]

    all_pcm = list(enc.emit_preamble())
    for pkt in packets:
        enc.feed_packet(pkt)
    while enc.has_data():
        chunk = enc.get_pcm_chunk()
        if chunk is not None:
            all_pcm.append(chunk)

    pcm_data = np.concatenate(all_pcm)
    partial_pcm = pcm_data[: len(pcm_data) // 2]  # Only first 50%

    # Play partial PCM through pipe
    # (Simplified - may need custom helper or inline sounddevice code)
    import sounddevice as sd

    with sd.OutputStream(device=pipe.sink_name, samplerate=16000, channels=1):
        with sd.InputStream(device=pipe.source_name, samplerate=16000, channels=1):
            # Stream partial data
            # Feed to decoder
            # Verify graceful handling (may decode 0-2 packets, no crash)
            pass

    # Verify: no exceptions, decoder state reasonable
    # Don't assert exact packet count (depends on where interruption happens)
    assert dec.get_state() in [DecoderState.SEARCH_PREAMBLE, DecoderState.LOCKED]
```

**Note:** This test is more exploratory - verifies no crashes, graceful degradation.

### Phase 5: Add Dependencies

**File:** [`pyproject.toml`](../pyproject.toml)

Add `sounddevice` to dependencies if not already present:

```toml
[project]
dependencies = [
    # ... existing dependencies ...
    "sounddevice>=0.4.6",
]
```

**Install:** `uv pip install sounddevice`

### Phase 6: Full Validation

**Run complete test suite:**

```bash
uv run pytest amodem_duplex/tests/test_pulseaudio_integration.py -v
```

**Expected results:**

- All 3 tests PASS (or SKIPPED if pactl not available)
- No failures
- Tests marked as `slow` and `integration`

**Run full amodem_duplex test suite:**

```bash
uv run pytest amodem_duplex/tests/ -v
```

**Verify:** No regressions in existing tests.

**Code quality checks:**

```bash
uv run black amodem_duplex/tests/test_pulseaudio_integration.py
uv run ruff check amodem_duplex/tests/test_pulseaudio_integration.py
```

**Fix any linter issues.**

### Phase 7: Write Comprehensive Report

Create [`reports/report007.md`](../reports/report007.md) documenting:

1. **Objective** - Integration tests with real PulseAudio pipes
2. **Summary** - What was implemented, why it matters
3. **Files Created** - List new test file
4. **Files Modified** - pyproject.toml (if sounddevice added)
5. **Technical Details**:
   - Test structure and fixtures
   - Helper method implementation
   - sounddevice integration
   - Synchronization strategy
   - Test coverage (3 smoke tests)
6. **Test Results**:
   - Individual test outputs
   - Full suite results
   - Execution time comparison (integration vs loopback)
7. **Validation** - How tests verify real audio I/O
8. **Known Limitations**:
   - Requires PulseAudio (tests skipped otherwise)
   - Slower than loopback tests (real-time audio)
   - Limited scope (smoke tests only, not comprehensive)
9. **Success Criteria** - All criteria met
10. **Alignment with AGENTS.md** - Following guidelines

**Follow the structure of:**

- [`reports/report001.md`](../reports/report001.md)
- [`reports/report002.md`](../reports/report002.md)
- [`reports/report003.md`](../reports/report003.md)
- [`reports/report004.md`](../reports/report004.md)
- [`reports/report005.md`](../reports/report005.md)
- [`reports/report006.md`](../reports/report006.md)

## Design Considerations

### Audio Library Choice

**Decision: Use `sounddevice`**

**Rationale:**

- Simpler API than `pyaudio`
- Native numpy array support (matches encoder/decoder)
- Better device selection (by name)
- Active maintenance

**Alternative considered:**

- `pyaudio` - More complex, less Pythonic, but more widely used

### Stream Synchronization

**Decision: Start recording before playback**

**Rationale:**

- Avoids missing the preamble (decoder needs it to lock)
- Simpler than complex callback synchronization
- Acceptable for tests (not latency-critical)

**Implementation:**

- Open input stream first
- Start recording with sufficient buffer
- Then open output stream and start playback
- Use blocking I/O for simplicity

### Test Scope

**Decision: Minimal smoke tests (3 tests)**

**Rationale:**

- Real-time audio is slow (tests take seconds, not milliseconds)
- Comprehensive scenarios already covered in [`test_loopback.py`](../amodem_duplex/tests/test_loopback.py)
- Integration tests just validate "it works end-to-end"
- Not meant to replace or duplicate loopback tests

**Coverage:**

- Single packet: Basic validation
- Multiple packets: Sequential encoding/decoding
- Interrupted: Graceful degradation

### Performance Impact

**Expected execution time:**

- Single packet: ~1-2 seconds (preamble + data + latency)
- Multiple packets: ~2-4 seconds (depends on packet count)
- Interrupted: ~1-2 seconds

**Total suite:** ~5-10 seconds (vs milliseconds for loopback tests)

**Mitigation:**

- Mark as `@pytest.mark.slow`
- Mark as `@pytest.mark.integration`
- Can be excluded from quick test runs: `pytest -m "not slow"`

### Edge Cases

**Handled:**

1. **pactl not available** - Skip all tests with pytest marker
2. **PulseAudio not running** - Tests will fail but won't crash (subprocess errors)
3. **Device busy** - May fail if sink/source already in use (acceptable for tests)
4. **Buffer underruns/overruns** - sounddevice handles gracefully

**Not handled (acceptable for smoke tests):**

- Comprehensive error injection (covered in loopback tests)
- Timing drift compensation (real audio is inherently noisy)
- Multiple simultaneous streams (not a test requirement)

## Files to Create

1. **[`amodem_duplex/tests/test_pulseaudio_integration.py`](../amodem_duplex/tests/test_pulseaudio_integration.py)** - Integration tests (~150-200 lines)

## Files to Modify

1. **[`pyproject.toml`](../pyproject.toml)** - Add `sounddevice` dependency (if not present)

## Files to Create (Report)

1. **[`reports/report007.md`](../reports/report007.md)** - Comprehensive implementation report

## Key Design Decisions

1. **Use sounddevice** - Simpler API, native numpy support
2. **Start recording first** - Avoid missing preamble
3. **Blocking I/O** - Simpler than callbacks for tests
4. **Minimal scope** - 3 smoke tests, not comprehensive
5. **Pytest markers** - `slow`, `integration`, skip if no pactl
6. **Real pipes** - No mocks, test against actual PulseAudio
7. **Helper method** - Reusable encode/decode logic
8. **Fixtures at top** - Per AGENTS.md guidelines
9. **TDD approach** - Skeleton first, then implementation
10. **Actually run tests** - Don't just claim ready

## Alignment with AGENTS.md

- ✅ **Keep it simple** - Minimal smoke tests, not over-engineered
- ✅ **Don't over-engineer** - Basic blocking I/O, no complex abstractions
- ✅ **Stay focused** - Just validate real audio I/O works
- ✅ **TDD methodology** - Skeleton first, then implementation
- ✅ **Actually run tests** - Required at each phase
- ✅ **Type annotations** - All fixture arguments typed
- ✅ **Fixtures at top** - Before test methods
- ✅ **No inline test classes** - Use fixtures instead
- ✅ **Mirror structure** - tests/ mirrors package structure
- ✅ **Format with black** - Explicit validation step
- ✅ **Check with ruff** - Explicit validation step
- ✅ **Write comprehensive report** - Following existing report style

## Success Criteria

- ✅ `test_single_packet_roundtrip` passes with real audio I/O
- ✅ `test_multiple_packets_roundtrip` passes with real audio I/O
- ✅ `test_interrupted_stream` passes (graceful handling)
- ✅ Tests skipped if pactl not available
- ✅ Tests marked as `slow` and `integration`
- ✅ No regressions in existing test suite
- ✅ No linter errors (black, ruff)
- ✅ sounddevice dependency added to pyproject.toml
- ✅ Comprehensive report written in reports/report007.md
- ✅ All tests actually run and pass (not just "ready for testing")

## Expected Outcome

After implementation, `amodem_duplex` will have:

- **Validated full stack** - Encoding → Real audio I/O → Decoding works end-to-end
- **PulseAudio integration** - Verified [`PulseAudioPipeManager`](../amodem_duplex/debugtools/pulseaudio_pipe.py) works in realistic scenario
- **Confidence in deployment** - Not just in-memory tests, but real audio constraints
- **Complementary coverage** - Loopback tests (fast, comprehensive) + Integration tests (slow, realistic)

**Test organization:**

- **Loopback tests** - Fast, deterministic, comprehensive scenarios
- **Integration tests** - Slow, realistic, basic smoke tests
- **Run separately** - Use pytest markers to exclude slow tests when needed
