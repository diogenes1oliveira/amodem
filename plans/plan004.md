# Fix Periodic Preamble Resync While Locked

## Background

Currently, the test suite has 175 tests with 168 passing, 3 skipped, and **4 xfailed**. One of these xfailed tests is `test_streaming_with_periodic_preambles` which demonstrates a critical limitation: the decoder cannot detect and resynchronize to new preambles when already in LOCKED state.

**CRITICAL RULES:**

- All changes in [`amodem_duplex/`](../amodem_duplex/) package ONLY
- **NO modifications to [`amodem/`](../amodem/) package** - only import from it
- Write comprehensive report at end (like [`reports/report001.md`](../reports/report001.md), [`reports/report002.md`](../reports/report002.md), and [`reports/report003.md`](../reports/report003.md))
- Follow guidelines in [`AGENTS.md`](../AGENTS.md)

## The Problem

**Status:** Not implemented (marked as xfailed in report003.md)

**Location:** [`amodem_duplex/decoder.py`](../amodem_duplex/decoder.py) lines 85-88

**Issue:** When decoder is LOCKED and receives a new preamble, it doesn't reinitialize. The decoder only searches for preambles when in `SEARCH_PREAMBLE` state.

**Current behavior:**

```python
def feed_pcm(self, samples: npt.NDArray[np.float64]) -> None:
    # Add to buffer
    self.pcm_buffer = np.concatenate([self.pcm_buffer, samples])

    # Process based on state
    if self.state == DecoderState.SEARCH_PREAMBLE:
        self._search_for_preamble()
    elif self.state == DecoderState.LOCKED:
        self._demodulate_locked()  # ❌ No preamble detection here!
```

Once locked, if a new preamble arrives, the decoder treats it as data, which causes CRC errors and eventually forces the decoder to drop back to SEARCH state (losing sync).

**Impact:** Applications need to manage sessions explicitly or use separate decoder instances for sessions with new preambles. This prevents true continuous streaming with periodic resynchronization.

**From report003.md:**

> "This prevents true continuous streaming with periodic resynchronization."

## The Solution

Enable the decoder to detect preambles **even while locked** to support:

- Long-running streaming sessions with periodic resynchronization
- Continuous data transmission without explicit session boundaries
- Automatic recovery from drift/timing issues
- Multiple consecutive sessions with preambles in a single stream

## Implementation Steps

### Step 1: Modify `feed_pcm()` method

**File:** [`amodem_duplex/decoder.py`](../amodem_duplex/decoder.py)

Add preamble correlation check before demodulation in LOCKED state:

```python
def feed_pcm(self, samples: npt.NDArray[np.float64]) -> None:
    # Add to buffer
    self.pcm_buffer = np.concatenate([self.pcm_buffer, samples])

    # Process based on state
    if self.state == DecoderState.SEARCH_PREAMBLE:
        self._search_for_preamble()
    elif self.state == DecoderState.LOCKED:
        self._check_preamble_while_locked()  # NEW - detect resync
        self._demodulate_locked()
```

**AGENTS.md Note:** Keep it simple - don't over-engineer. Just add the minimal logic needed for preamble detection while locked.

### Step 2: Add `_check_preamble_while_locked()` method

**File:** [`amodem_duplex/decoder.py`](../amodem_duplex/decoder.py)

Create a new method that:

1. **Runs correlation on PCM buffer** (similar to `_search_for_preamble()`)
2. **If strong correlation found** (> 0.3 threshold, same as SEARCH state):
   - Clear `bit_buffer` (discard incomplete frames from previous session)
   - Clear `packet_queue` (clean session boundary)
   - Align `pcm_buffer` to preamble end
   - Re-initialize demodulation with `_init_demodulation()`
   - Reset consecutive errors counter
   - Stay in LOCKED state (no state transition)

**Implementation approach:**

```python
def _check_preamble_while_locked(self) -> None:
    """Check for new preamble while locked (for resync)."""
    preamble_len = len(self.preamble_pcm)

    # Need enough buffer to correlate
    if len(self.pcm_buffer) < preamble_len:
        return

    # Compute correlation (reuse logic from _search_for_preamble)
    correlation = np.correlate(
        self.pcm_buffer[: preamble_len * 2] if len(self.pcm_buffer) >= preamble_len * 2 else self.pcm_buffer,
        self.preamble_pcm,
        mode="valid",
    )

    if len(correlation) > 0:
        max_corr = np.max(np.abs(correlation))
        preamble_energy = np.linalg.norm(self.preamble_pcm)
        norm_corr = max_corr / (preamble_energy * np.sqrt(preamble_len))

        # If strong correlation detected, resync
        if norm_corr > 0.3:
            peak_idx = np.argmax(np.abs(correlation))

            # Clear session state for clean resync
            self.bit_buffer = []
            self.packet_queue = []

            # Align to new preamble
            self.pcm_buffer = self.pcm_buffer[peak_idx + preamble_len :]

            # Re-initialize demodulation
            self._init_demodulation()
            # Stay in LOCKED state
```

**AGENTS.md Notes:**

- **Keep it simple**: Reuse existing correlation logic from `_search_for_preamble()`
- **Don't over-engineer**: No configuration flags, no complex state tracking
- **Type annotations**: Method signature follows existing patterns

### Step 3: Update the xfail test

**File:** [`amodem_duplex/tests/test_realistic_scenarios.py`](../amodem_duplex/tests/test_realistic_scenarios.py)

Remove the `@pytest.mark.xfail` decorator from `test_streaming_with_periodic_preambles` (around line 238).

**Current:**

```python
@pytest.mark.xfail(reason="Resync while locked not implemented")
def test_streaming_with_periodic_preambles(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
```

**Change to:**

```python
def test_streaming_with_periodic_preambles(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
```

### Step 4: Run the specific test

**AGENTS.md Note:** "If you changed a test, you are to actually test it; don't just say it's ready for testing unless I tell you I'm gonna test manually."

Run the test to verify it passes:

```bash
uv run pytest amodem_duplex/tests/test_realistic_scenarios.py::TestRealisticScenarios::test_streaming_with_periodic_preambles -v
```

Expected result: Test should PASS (not xfail)

### Step 5: Validate with full test suite

Run all tests to ensure no regressions:

```bash
uv run pytest amodem_duplex/tests/ -v
```

Expected results:

- **169 tests passed** (168 previously passing + 1 previously xfailed)
- **3 skipped** (unavailable configs)
- **3 xfailed** (remaining known issues)
- **0 failures**

### Step 6: Code quality checks

**AGENTS.md Note:** "Format your code with black" and "To check out unused imports, use ruff"

```bash
uv run black amodem_duplex/decoder.py amodem_duplex/tests/test_realistic_scenarios.py
uv run ruff check amodem_duplex/decoder.py
```

Fix any linter issues if they arise.

### Step 7: Write comprehensive report

Create [`reports/report004.md`](../reports/report004.md) documenting:

1. **Summary** - What was implemented
2. **The Problem** - Why periodic preamble resync was needed
3. **The Solution** - How it was implemented
4. **Implementation Details** - Code changes with line numbers
5. **Test Results** - Before/after comparison
6. **Validation** - Specific test results and full suite results
7. **Performance** - Any impact on execution time
8. **Known Limitations** - Remaining xfailed tests
9. **Alignment with AGENTS.md** - How we followed the guidelines
10. **Files Modified** - List of all changed files
11. **Conclusion** - Summary of achievement

**AGENTS.md Note:** Follow the structure of report001.md, report002.md, and report003.md for consistency.

## Design Considerations

### Keep It Simple (per AGENTS.md)

- **Don't over-engineer**: Reuse existing correlation logic
- **No new configuration**: Use same 0.3 threshold as SEARCH state
- **No complex state tracking**: Just detect, clear, reinitialize

### What to Clear on Resync?

**Decision: Clear both `bit_buffer` and `packet_queue`**

**Rationale:**

- Clean session boundaries
- Avoid mixing data from different sessions
- Matches user expectations (new preamble = new session)
- Simpler behavior (no partial state retention)

**Alternative considered but rejected:**

- Keep `packet_queue` to deliver buffered packets → Too complex, ambiguous semantics

### Performance Impact

- Correlation is cheap (already done in SEARCH state)
- Only adds computation when LOCKED (but most time is in demodulation anyway)
- Low overhead: O(preamble_length) correlation per `feed_pcm()` call

### Edge Cases Handled

1. **Preamble at exact buffer boundary** - Correlation uses sliding window
2. **Weak preamble (< 0.3 threshold)** - Ignored, continue normal operation
3. **Partial preamble** - Not enough buffer, correlation skipped
4. **Multiple preambles back-to-back** - Each one triggers resync (idempotent)

## Files to Modify

1. **[`amodem_duplex/decoder.py`](../amodem_duplex/decoder.py)**

   - Modify `feed_pcm()` method (lines 85-88)
   - Add `_check_preamble_while_locked()` method (new method)

2. **[`amodem_duplex/tests/test_realistic_scenarios.py`](../amodem_duplex/tests/test_realistic_scenarios.py)**

   - Remove `@pytest.mark.xfail` decorator (line ~238)

3. **[`reports/report004.md`](../reports/report004.md)** - NEW FILE
   - Comprehensive report following format of previous reports

## Success Criteria

- ✅ `test_streaming_with_periodic_preambles` passes without xfail
- ✅ All 169 tests pass (168 + 1 newly passing)
- ✅ No regressions in existing tests
- ✅ No new linter errors (black, ruff, mypy)
- ✅ Decoder can handle multiple consecutive sessions with preambles in single stream
- ✅ Comprehensive report written documenting the implementation

## Alignment with AGENTS.md

1. **Keep it simple** ✅ - Only implement what's explicitly needed (preamble detection while locked)
2. **Don't over-engineer** ✅ - Reuse existing code, no new abstractions
3. **Stay focused** ✅ - Fix one specific issue: periodic preamble resync
4. **Always add type annotations** ✅ - Method follows existing type annotation patterns
5. **Actually test it** ✅ - Run pytest on modified tests, not just claim ready
6. **Format with black** ✅ - Explicit step in validation
7. **Use ruff** ✅ - Check for unused imports and errors
8. **No modifications to amodem/** ✅ - Only changes in amodem_duplex/

## Expected Outcome

After implementation, `amodem_duplex` will support **true continuous streaming** with periodic preambles, enabling:

- Long-running streaming sessions without explicit session management
- Automatic resynchronization without dropping to SEARCH state
- Simplified application code (no need to manage multiple decoder instances)
- Better alignment with real-world streaming use cases

Test count will change from:

- **Before**: 168 passed, 3 skipped, 4 xfailed
- **After**: 169 passed, 3 skipped, 3 xfailed (1 xfail fixed)
