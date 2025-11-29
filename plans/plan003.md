# Realistic Streaming Test Scenarios & Multiple Packets Bug Fix

## Background

Current test suite has 148 tests covering edge cases and failures, but they're isolated tests. The **critical bug preventing multiple consecutive packets from decoding** needs to be fixed - this is the core reason `amodem_duplex` exists. We need realistic usage patterns that demonstrate how applications would actually use this library.

**CRITICAL RULES:**

- All changes in [`amodem_duplex/`](amodem_duplex/) package ONLY
- **NO modifications to [`amodem/`](amodem/) package** - only import from it
- Write comprehensive report at end (like [`reports/report001.md`](reports/report001.md) and [`reports/report002.md`](reports/report002.md))

## The Critical Bug

**Location:** [`amodem_duplex/decoder.py`](amodem_duplex/decoder.py) lines 214-221

**Issue:** After decoding first packet with EOF, `_extract_frames()` clears entire `bit_buffer`, preventing subsequent packets from being decoded.

**Current code:**

```python
if packets_decoded > 0:
    self.bit_buffer = []  # ❌ Clears ALL bits
```

**Required fix:** Only clear consumed bits, keep remaining bits for next packet. The `amodem.framing.Framer.decode()` generator stops at first EOF - need to restart framing logic to process next packet in remaining bits.

## Implementation Steps

### Step 1: Fix the Multiple Packets Bug

Modify [`amodem_duplex/decoder.py`](amodem_duplex/decoder.py) `_extract_frames()` method:

- Track how many bits were consumed by the framer
- After EOF, don't clear entire bit_buffer
- Create new Framer instance to restart decoding for next packet
- Keep remaining unconsumed bits in buffer

### Step 2: Create Realistic Test Scenarios

Create [`amodem_duplex/tests/test_realistic_scenarios.py`](amodem_duplex/tests/test_realistic_scenarios.py) with 21 tests across 5 categories:

**1. Chat/Messaging (5 tests)** - Small frequent packets simulating text communication

**2. File Transfer (4 tests)** - Data split into chunks with acknowledgments

**3. Request-Response (4 tests)** - API-like bidirectional patterns

**4. Continuous Streaming (5 tests)** - Long sessions with heartbeats and periodic preambles

**5. Mixed Workloads (3 tests)** - Combined patterns in one session

Each test will:

1. Encode multiple packets with single preamble
2. Feed all PCM to decoder
3. Extract ALL decoded packets
4. Verify all packets received correctly

### Step 3: Run Tests & Validate

1. Run new tests FIRST (should fail with current code)
2. Apply decoder fix
3. Run tests again (should pass)
4. Run full test suite (148 existing + 21 new = 169 total)
5. Format with black, check with ruff

### Step 4: Write Comprehensive Report

Create [`reports/report003.md`](reports/report003.md) documenting:

- Summary of realistic scenarios added
- Details of the multiple packets bug fix
- Before/after comparison
- Test results (all 169 tests)
- Validation that consecutive packets now work

## Files to Modify/Create

1. [`amodem_duplex/decoder.py`](amodem_duplex/decoder.py) - Fix `_extract_frames()` method
2. [`amodem_duplex/tests/test_realistic_scenarios.py`](amodem_duplex/tests/test_realistic_scenarios.py) - NEW (21 tests)
3. [`reports/report003.md`](reports/report003.md) - NEW comprehensive report

## Success Criteria

- All 21 new realistic scenario tests pass
- Multiple consecutive packets decode successfully
- No regressions in existing 148 tests
- Zero linter errors
- Demonstrates amodem_duplex works for real-world use cases
