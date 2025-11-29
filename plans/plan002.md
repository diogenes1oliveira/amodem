# Comprehensive Failure Mode Testing (TDD)

**Goal:** Add thorough tests for edge cases and failure modes in encoder and decoder that aren't currently covered.

**Approach:** Strict TDD - write tests with expectations first, run them, then document if code changes are needed and why.

## Background

Based on analysis of [`reports/report001.md`](../reports/report001.md) and existing tests, we have 56 passing tests but several known limitations and untested failure modes.

### Current Coverage (56 tests)

- Basic encoding/decoding functionality ✅
- Single packet transmission ✅
- Preamble detection ✅
- Heartbeat mechanism ✅
- Basic corruption handling ✅
- Various packet sizes ✅

### Known Gaps from Report

1. **Multiple consecutive packets** - Only first packet reliably decoded
2. **Preamble while locked** - May cause confusion/CRC errors
3. **High bitrate configs** - Only tested with `slowest()` config
4. **Timing edge cases** - Buffer overflow scenarios
5. **Memory/stress testing** - Long-running behavior unknown
6. **Partial/truncated data** - Incomplete chunks/frames

## Test Files to Create

### 1. `amodem_duplex/tests/test_encoder_failures.py`

Encoder-specific failure modes to test:

#### Input Validation

- **test_empty_packet** - Feed empty bytes `b""`
- **test_feed_packet_with_none** - Try to feed `None` instead of bytes
- **test_feed_packet_with_string** - Try to feed string instead of bytes
- **test_feed_packet_with_int** - Try to feed integer

#### Memory/Buffer Management

- **test_rapid_feed_without_draining** - Feed many packets before calling `get_pcm_chunk()`
- **test_bit_buffer_partial_symbols** - Verify bit buffer handles partial symbol bits correctly
- **test_pcm_buffer_fragmentation** - Many small chunks leading to deque growth
- **test_multiple_preamble_emissions** - Emit preamble multiple times in quick succession

#### Configuration Edge Cases

- **test_zero_chunk_samples** - Initialize with `chunk_samples=0`
- **test_negative_chunk_samples** - Initialize with negative chunk_samples
- **test_zero_heartbeat_interval** - Initialize with `heartbeat_interval=0`
- **test_negative_preamble_interval** - Initialize with negative preamble_interval

#### Timing Edge Cases

- **test_clock_jumping_forward** - Mock clock with large time jumps
- **test_heartbeat_spam** - Call `send_heartbeat()` repeatedly
- **test_needs_preamble_at_exact_interval** - Test boundary condition at exact interval
- **test_needs_heartbeat_at_exact_interval** - Test boundary condition at exact interval

#### State Management

- **test_preamble_emission_while_data_queued** - Emit preamble with pending packets
- **test_get_pcm_chunk_exhaustive_drain** - Keep calling get_pcm_chunk until truly empty
- **test_has_data_after_partial_chunk** - When buffer has less than chunk_samples

### 2. `amodem_duplex/tests/test_decoder_failures.py`

Decoder-specific failure modes to test:

#### Preamble Detection Edge Cases

- **test_truncated_preamble** - Feed partial preamble and stop
- **test_repeated_preambles_while_locked** - Feed multiple preambles back-to-back while locked
- **test_preamble_with_phase_shift** - Feed preamble with phase offset
- **test_inverted_preamble** - Feed negated preamble (180° phase)
- **test_weak_preamble** - Feed preamble with very low amplitude

#### Frame Decoding Edge Cases

- **test_malformed_frame_header** - Invalid frame header structure
- **test_wrong_frame_crc** - Correct structure but wrong CRC
- **test_eof_without_data** - Send just EOF frame marker
- **test_double_eof_frames** - Multiple EOFs in sequence
- **test_frame_with_invalid_length** - Frame claims invalid length

#### Buffer Management

- **test_bit_buffer_overflow** - Accumulate bits without valid frames (>10k bits)
- **test_pcm_buffer_overflow** - Feed massive amounts of random PCM
- **test_partial_symbol_boundaries** - Feed PCM that doesn't align with Nsym
- **test_bit_buffer_at_exact_threshold** - Fill buffer to exactly 4000 bits
- **test_consecutive_errors_at_threshold** - Exactly N consecutive errors

#### Signal Quality

- **test_zero_amplitude_signal** - Feed all zeros after lock
- **test_maximum_amplitude_saturation** - Feed clipped/saturated signals
- **test_extremely_low_snr** - Heavy noise after preamble
- **test_dc_offset** - Signal with large DC component
- **test_sudden_amplitude_change** - Amplitude jumps during decoding

#### State Machine

- **test_feed_pcm_massive_chunks** - Single huge PCM array (>100k samples)
- **test_feed_pcm_tiny_chunks** - Feed 1 sample at a time
- **test_get_packet_spam** - Call get_packet() many times when empty
- **test_stats_during_search** - Verify stats are reasonable in SEARCH state
- **test_stats_during_locked** - Verify stats update in LOCKED state

#### Configuration Edge Cases

- **test_crc_error_threshold_zero** - Initialize with threshold=0
- **test_crc_error_threshold_large** - Initialize with threshold=100

### 3. `amodem_duplex/tests/test_loopback_failures.py`

Integration failure modes to test:

#### Transmission Integrity

- **test_partial_transmission** - Encoder produces PCM but only feed first 50% to decoder
- **test_partial_transmission_at_frame_boundary** - Stop exactly at frame boundary
- **test_dropped_chunks_periodic** - Skip every Nth chunk (N=2, 3, 5)
- **test_dropped_chunks_random** - Randomly drop 30% of chunks
- **test_duplicated_chunks** - Feed same chunk twice in sequence
- **test_out_of_order_chunks** - Shuffle PCM chunks before feeding

#### Session Management

- **test_decoder_reuse_without_reset** - Use same decoder instance for multiple sessions
- **test_encoder_reuse_multiple_packets** - Same encoder for multiple packets with preambles
- **test_interleaved_sessions** - Mix PCM from two different encoder sessions
- **test_decoder_multiple_locks** - Decoder locks, unlocks, relocks multiple times

#### Configuration Mismatches

- **test_mismatched_configs_different_speeds** - Encoder with `fast()`, decoder with `slowest()`
- **test_mismatched_configs_different_freqs** - Different carrier frequencies
- **test_mismatched_configs_different_symbols** - Different modulation schemes

#### Timing and Synchronization

- **test_preamble_overlap** - Two preambles with partial overlap
- **test_heartbeat_flood** - Only heartbeats, no real data for extended period
- **test_alternating_valid_invalid** - Valid packet, corrupted, valid, corrupted pattern
- **test_missing_preamble** - Feed data without initial preamble
- **test_late_preamble** - Feed data, then preamble later

#### Buffer Boundary Conditions

- **test_buffer_starvation** - Decoder with minimal PCM (less than one symbol)
- **test_crc_threshold_boundary_minus_one** - Exactly N-1 consecutive errors
- **test_crc_threshold_boundary_exact** - Exactly N consecutive errors
- **test_crc_threshold_boundary_plus_one** - Exactly N+1 consecutive errors

#### Complex Corruption Scenarios

- **test_corruption_in_preamble** - Corrupt part of preamble
- **test_corruption_in_header** - Corrupt frame header
- **test_corruption_in_payload** - Corrupt frame payload but not CRC field
- **test_corruption_in_crc_field** - Corrupt only the CRC bytes
- **test_gradual_corruption_increase** - Corruption increases over time

### 4. `amodem_duplex/tests/test_config_variations.py`

Configuration-specific tests:

#### Multiple Configurations

- **test_slowest_config** - Full round trip with `slowest()`
- **test_slow_config** - Full round trip with `slow()` (if exists)
- **test_fast_config** - Full round trip with `fast()` (if exists)
- **test_fastest_config** - Full round trip with `fastest()` (if exists)

#### Parameter Variations (Parametrized Tests)

- **test_various_chunk_sizes** - Test with chunk_samples = [64, 320, 640, 1280, 2560]
- **test_various_heartbeat_intervals** - Test with [0.1, 0.5, 1.0, 5.0, 10.0] seconds
- **test_various_preamble_intervals** - Test with [1.0, 3.0, 10.0, 30.0] seconds
- **test_various_crc_thresholds** - Test with threshold = [1, 3, 5, 10]

#### Stress Tests

- **test_1000_packets_round_trip** - Encode and decode 1000 packets in sequence
- **test_packet_size_range** - Test all sizes from 1 byte to 1000 bytes
- **test_long_session_memory** - Run encoder/decoder for extended period, check memory

## Implementation Steps

### Phase 1: Create Test Skeletons (All 4 Files)

**CRITICAL (per AGENTS.md):** Start with skeletons only, then STOP and ask how to proceed!

For each test file:

1. Create file with header: `# mypy: disable-error-code="no-untyped-def"`
2. Add imports (pytest, numpy, amodem.config, encoder, decoder)
3. Add test class
4. **Define all fixtures at TOP of class** (config, mock_clock, enc, dec as needed)
5. Add all test method signatures with single `pass` statement
6. NO comments in test methods (names should be descriptive)
7. Run `uv run pytest amodem_duplex/tests/` to verify structure

### Phase 2: Implement Tests with Expectations (TDD)

For each test method, use this structure (per AGENTS.md):

1. **Write test with standard blocks (NO block label comments):**

   ```python
   def test_something(self, enc: encoder.StreamEncoder):
       # Setup
       test_data = b"test"

       # Act
       enc.feed_packet(test_data)
       result = enc.get_pcm_chunk()

       # Verify
       assert result is not None
   ```

2. **Use existing fixtures** - Don't create new ones unless absolutely necessary

   - Prefer configuring mocks with `side_effect` over inline test classes
   - All fixtures at top of test class

3. **Actually RUN the test** (per AGENTS.md rule):

   - `uv run pytest path/to/test.py::TestClass::test_method -v`
   - Don't just say "ready for testing"

4. **Document result** - One of:

   - ✅ PASS - Behavior matches expectation
   - ❌ FAIL - Bug found, needs fix
   - ⚠️ UNEXPECTED - Differs from expectation
   - 📝 LIMITATION - Known limitation

5. **Note needed changes** (if test fails):
   - What? (validation, error handling, buffer management)
   - Why? (prevent crash, improve UX, fix bug)
   - Where? (encoder.py lines X-Y, decoder.py function Z)

### Phase 3: Run All Tests and Create Report

After implementing all tests:

1. Run full suite: `uv run pytest amodem_duplex/tests/ -v`
2. Check linter: `uv run ruff check amodem_duplex/tests/`
3. Format code: `uv run black amodem_duplex/tests/`
4. Fix any mypy errors
5. Create `reports/report002.md` with:
   - Summary of new tests added
   - Categorization of results (pass, fail, limitation)
   - List of bugs found (critical, medium, low)
   - List of code changes made
   - Updated test metrics

### Phase 4: Fix Critical Bugs (If Any)

Fix bugs revealed by tests (prioritized):

**High Priority (Core Functionality):**

- Multiple consecutive packets - Should work, decoder needs to restart framing after EOF
- Preamble while locked - Should NOT break decoding, needed for periodic re-sync
- Crashes/exceptions that shouldn't happen
- Data corruption issues

**Medium Priority:**

- Memory leaks or unbounded growth
- Incorrect state transitions
- Buffer management issues

**Low Priority / Won't Fix:**

- Config mismatches (undefined behavior - document only)
- Out-of-order chunks (application layer responsibility)
- Extreme edge cases that don't affect real usage

## Testing Principles (Per AGENTS.md)

### Critical Rules

1. **Start with skeletons (pass statements) - STOP - Ask user before implementing**
2. **Use standard setup/act/verify blocks - NO comments labeling them**
3. **Define all fixtures at TOP of test class**
4. **Avoid creating new fixtures** - use existing ones, configure with side_effect
5. **No inline test classes** - use fixtures with mocks instead
6. **Test names are descriptive - minimal comments needed**
7. **Actually RUN tests** - don't say "ready for testing"
8. **Type annotations on fixture args only** (not return values)

### Code Style

- Header: `# mypy: disable-error-code="no-untyped-def"`
- Use `uv` for all Python commands
- Format with: `uv run black`
- Check with: `uv run ruff check`
- Full module imports (not relative, except in `__init__.py`)

### Patterns

- `pytest.raises(TypeError)` for type errors
- `pytest.raises(ValueError)` for value errors
- `pytest.mark.parametrize` for variations
- Use pytest fixtures: `tmp_path`, `monkeypatch`, etc.
- Mock clock for timing tests (already have fixture)

### Example Test Structure

```python
def test_empty_packet(self, config: amodem.config.Configuration):
    enc = encoder.StreamEncoder(config)

    enc.feed_packet(b"")
    result = enc.has_data()

    assert result is False
```

(No comments for setup/act/verify - code structure shows this)

## Expected Outcomes

### Tests That Should Pass (Graceful Degradation)

- Corrupted data → decoder drops lock or ignores
- Buffer overflows → decoder trims/resets buffers
- Invalid inputs → raise clear exceptions with messages
- Missing preamble → decoder stays in SEARCH

### Tests That May Reveal Bugs

- Bit buffer overflow → potential memory issue
- PCM buffer unbounded growth → memory leak
- Multiple EOFs → decoder stuck in loop
- State transitions → deadlock or crash
- Type errors → missing validation

### Tests That Should Reveal Bugs to Fix

- **Multiple consecutive packets** → decoder stops after first EOF (NEEDS FIX)
- **Preamble while locked** → causes CRC errors (NEEDS FIX)
- Bit buffer overflow → unbounded growth (NEEDS FIX if found)
- PCM buffer growth → memory leak (NEEDS FIX if found)

### Tests That Document Limitations (Won't Fix)

- Config mismatches → undefined behavior
- Out-of-order chunks → corruption (application layer issue)
- Extreme signal conditions beyond design specs

## Files Potentially Affected

Expected code changes to fix known issues:

### [`amodem_duplex/decoder.py`](../amodem_duplex/decoder.py) (High Priority)

**Multiple consecutive packets issue:**

- After decoding frame with EOF, don't stop framing generator
- Restart framing logic to look for next frame
- Don't clear bit_buffer entirely after extracting one packet
- Keep scanning for frame headers in remaining bits

**Preamble while locked issue:**

- Continue running correlation check even in LOCKED state (low overhead)
- When preamble detected while locked, re-initialize equalizer without losing state
- Or: treat new preamble as "soft reset" - clear bit buffer but stay locked

**Buffer management:**

- Add maximum size limits for bit_buffer and pcm_buffer
- Better cleanup strategy for processed bits
- Prevent unbounded growth in long-running sessions

### [`amodem_duplex/encoder.py`](../amodem_duplex/encoder.py) (Medium Priority)

- Add input validation in `feed_packet()` (TypeError for non-bytes)
- Add parameter validation in `__init__()` (ValueError for invalid intervals)
- Add buffer size limits if needed

### May add utility modules (Low Priority)

- `amodem_duplex/validation.py` - Input validation helpers
- `amodem_duplex/exceptions.py` - Custom exception types

## Success Criteria

1. **At least 50 new tests added** across 4 test files
2. **All tests have clear expectations** documented in code
3. **Test results documented** in report002.md
4. **Any bugs found are fixed** or documented as wont-fix
5. **Zero test failures** - all tests either pass or are marked xfail with reason
6. **Linter clean** - no mypy or ruff errors
7. **Comprehensive report** - future developers understand limitations

## Notes

- Following AGENTS.md: TDD strict, start with skeletons, ask before proceeding
- Tests mirror structure: `amodem_duplex/tests/test_*.py`
- All intermediate `__init__.py` files exist (already present)
- Use `uv` for all Python commands
- No extremely large packet tests (per user request)
- No clock going backwards tests (per user request)
- Keep it simple - don't over-engineer
