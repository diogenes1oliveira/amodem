# Sans-I/O Streaming Layer (TDD in amodem_duplex)

**CRITICAL RULES:**

- All new code in `amodem_duplex/` package (NOT `amodem/`)
- NO modifications to `amodem/` - only import
- Strict TDD: Write tests FIRST, then implement
- Skeleton: signatures/docstrings only, NO code before tests

## Phase 1: Preamble Helper

### 1.1 Create `amodem_duplex/tests/__init__.py`

Test module structure.

### 1.2 Create `amodem_duplex/preamble.py` - SKELETON ONLY

Signatures with docstrings:

- `generate_preamble_pcm(config) -> np.ndarray`
- `get_preamble_duration(config) -> float`

NO implementation yet.

### 1.3 Create `amodem_duplex/tests/test_preamble.py` - TESTS FIRST

Test cases for:

- Preamble PCM shape/length
- Contains prefix (carrier) and training
- Duration calculation
- Matches `amodem.send.Sender.start()` output

### 1.4 Implement `amodem_duplex/preamble.py`

Implement to pass tests. Import from [`amodem/send.py`](amodem/send.py), [`amodem/equalizer.py`](amodem/equalizer.py).

## Phase 2: Encoder with Heartbeat

### 2.1 Create `amodem_duplex/encoder.py` - SKELETON ONLY

`StreamEncoder` class signatures:

- `__init__(config, chunk_samples=640, heartbeat_interval=1.0, preamble_interval=3.0, clock_func=time.monotonic)`
- `emit_preamble() -> Iterator[np.ndarray]`
- `feed_packet(payload: bytes)`
- `get_pcm_chunk() -> Optional[np.ndarray]`
- `has_data() -> bool`
- `needs_preamble() -> bool` - uses internal clock tracking
- `needs_heartbeat() -> bool` - uses internal clock tracking
- `send_heartbeat()`

Notes:

- Sample rate from `config.Fs` (e.g., 16000 Hz)
- `chunk_samples` defines PCM chunk size
- `clock_func` injectable for testing, defaults to `time.monotonic`
- Tracks time internally for preamble/heartbeat intervals

Heartbeat: marker bytes `b'\x00\x00HEARTBEAT\x00\x00'`, separate from preamble.

NO implementation yet.

### 2.2 Create `amodem_duplex/tests/test_encoder.py` - TESTS FIRST

Test cases for:

- Preamble emission (correct PCM chunks)
- Packet queuing and PCM generation
- Internal buffering (partial chunks)
- Chunk size consistency
- Periodic preamble timing
- Heartbeat timing (needs_heartbeat when idle)
- Heartbeat packet generation (marker bytes)
- Heartbeat vs preamble independence
- Multiple packets
- Empty state returns None

### 2.3 Implement `amodem_duplex/encoder.py`

Implement to pass tests. Import from [`amodem/send.py`](amodem/send.py), [`amodem/framing.py`](amodem/framing.py).

## Phase 3: Decoder with State Machine

### 3.1 Create `amodem_duplex/decoder.py` - SKELETON ONLY

`DecoderState` enum: SEARCH_PREAMBLE, LOCKED

`StreamDecoder` class signatures:

- `__init__(config, crc_error_threshold=3)`
- `feed_pcm(samples: np.ndarray)`
- `get_packet() -> Optional[bytes]`
- `get_state() -> DecoderState`
- `get_stats() -> dict`
- `is_heartbeat(packet: bytes) -> bool` - detect heartbeat packets

State machine:

- SEARCH_PREAMBLE: sliding correlation, on hit → init equalizer → LOCKED
- LOCKED: demodulate, extract frames, track CRC errors, drop to SEARCH_PREAMBLE on threshold

NO implementation yet.

### 3.2 Create `amodem_duplex/tests/test_decoder.py` - TESTS FIRST

Test cases for:

- Initial state is SEARCH_PREAMBLE
- Random PCM keeps SEARCH_PREAMBLE
- Valid preamble → LOCKED transition
- Packet extraction in LOCKED
- Heartbeat packet detection
- CRC error tracking
- Consecutive CRC failures → SEARCH_PREAMBLE
- Stats reporting
- PCM buffering

### 3.3 Implement `amodem_duplex/decoder.py`

Implement to pass tests. Import from [`amodem/detect.py`](amodem/detect.py), [`amodem/recv.py`](amodem/recv.py), [`amodem/framing.py`](amodem/framing.py).

## Phase 4: Integration

### 4.1 Create `amodem_duplex/tests/test_loopback.py` - TESTS FIRST

End-to-end test cases:

- Single packet round-trip
- Multiple packets
- Periodic preamble resync
- Heartbeat during idle periods
- Decoder ignores heartbeats (or logs them)
- Decoder recovers after sync loss
- Various packet sizes
- Silence/gaps between packets
- Corrupted data handling

### 4.2 Fix integration issues

Debug encoder/decoder to pass loopback tests.

## Implementation Details

- Location: `amodem_duplex/` package
- Sample rate: from `config.Fs` (typically 16000 Hz)
- Chunk size: 640 samples @ 16kHz (40ms), configurable via `chunk_samples`
- Heartbeat interval: 1.0 second (configurable)
- Preamble interval: 3.0 seconds (configurable)
- CRC error threshold: 3 consecutive failures
- Heartbeat marker: `b'\x00\x00HEARTBEAT\x00\x00'`
- Clock function: `time.monotonic` by default, injectable for testing
- Encoder/decoder track time internally using `clock_func()`

## Import From (DO NOT MODIFY)

- [`amodem/send.py`](amodem/send.py)
- [`amodem/recv.py`](amodem/recv.py)
- [`amodem/framing.py`](amodem/framing.py)
- [`amodem/detect.py`](amodem/detect.py)
- [`amodem/equalizer.py`](amodem/equalizer.py)
- [`amodem/config.py`](amodem/config.py)
- [`amodem/dsp.py`](amodem/dsp.py)
