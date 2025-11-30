"""Stream decoder for sans-I/O packet decoding with state machine."""

import collections
import enum
import struct

import numpy as np
import numpy.typing as npt

import amodem.config
import amodem.detect
import amodem.dsp
import amodem.framing
import amodem.sampling
from amodem_duplex.protocol import encoder, preamble


class DecoderState(enum.Enum):
    """Decoder state machine states."""

    SEARCH_PREAMBLE = "search_preamble"
    LOCKED = "locked"


class StreamDecoder:
    """Sans-I/O decoder that converts PCM chunks to packets with state machine.

    This decoder:
    - Accepts PCM chunks via feed_pcm()
    - Searches for preamble to synchronize
    - Demodulates and extracts packets when LOCKED
    - Tracks CRC errors and drops back to SEARCH_PREAMBLE on failures
    - Can detect heartbeat packets
    """

    def __init__(
        self,
        config: amodem.config.Configuration,
        crc_error_threshold: int = 3,
        preamble_correlation_threshold: float = 0.3,
        frame_extraction_limit: int = 200,
        bit_buffer_resync_threshold: int = 4000,
    ) -> None:
        """Initialize the stream decoder.

        Args:
            config: amodem configuration object
            crc_error_threshold: Number of consecutive CRC failures before dropping lock
            preamble_correlation_threshold: Normalized correlation threshold for preamble detection (0.0-1.0)
            frame_extraction_limit: Maximum frames to extract per demodulation cycle (safety limit)
            bit_buffer_resync_threshold: Bit buffer size threshold for triggering resync on CRC errors
        """
        self.config = config
        self.crc_error_threshold = crc_error_threshold
        self.preamble_correlation_threshold = preamble_correlation_threshold
        self.frame_extraction_limit = frame_extraction_limit
        self.bit_buffer_resync_threshold = bit_buffer_resync_threshold

        # State
        self.state = DecoderState.SEARCH_PREAMBLE

        # PCM buffer
        self.pcm_buffer: npt.NDArray[np.float64] = np.array([], dtype=np.float64)

        # Separate buffer for preamble detection while locked
        self.preamble_check_buffer: npt.NDArray[np.float64] = np.array([], dtype=np.float64)

        # Packet queue (decoded packets waiting to be retrieved)
        self.packet_queue: collections.deque[bytes] = collections.deque()

        # Bit buffer (for frame extraction)
        self.bit_buffer: list[int] = []

        # Stats tracking
        self.stats = {
            "correlation": 0.0,
            "crc_errors": 0,
            "consecutive_errors": 0,
            "snr": 0.0,
        }

        # Demodulation components (created when locked)
        self.modem: amodem.dsp.MODEM | None = None

        # Preamble detection
        self.detector = amodem.detect.Detector(config=config, pylab=amodem.common.Dummy())
        self.preamble_pcm = preamble.generate_preamble_pcm(config)

    def feed_pcm(self, samples: npt.NDArray[np.float64]) -> None:
        """Feed incoming PCM samples to the decoder.

        Args:
            samples: Raw PCM samples as numpy array
        """
        # Add to buffer
        self.pcm_buffer = np.concatenate([self.pcm_buffer, samples])

        # Process based on state
        if self.state == DecoderState.SEARCH_PREAMBLE:
            self._search_for_preamble()
        elif self.state == DecoderState.LOCKED:
            # Also accumulate in preamble check buffer for resync detection
            self.preamble_check_buffer = np.concatenate([self.preamble_check_buffer, samples])

            self._check_preamble_while_locked()
            self._demodulate_locked()

    def _search_for_preamble(self) -> None:
        """Search for preamble in buffered PCM."""
        preamble_len = len(self.preamble_pcm)

        # Need at least preamble length to correlate
        if len(self.pcm_buffer) < preamble_len:
            return

        # Compute sliding correlation
        # Correlate buffer with preamble
        correlation = np.correlate(
            self.pcm_buffer[: preamble_len * 2] if len(self.pcm_buffer) >= preamble_len * 2 else self.pcm_buffer,
            self.preamble_pcm,
            mode="valid",
        )

        if len(correlation) > 0:
            max_corr = np.max(np.abs(correlation))
            # Normalize correlation
            preamble_energy = np.linalg.norm(self.preamble_pcm)
            norm_corr = max_corr / (preamble_energy * np.sqrt(preamble_len))

            self.stats["correlation"] = float(norm_corr)

            # If strong correlation, transition to LOCKED
            if norm_corr > self.preamble_correlation_threshold:
                # Find the peak
                peak_idx = np.argmax(np.abs(correlation))

                # Align to preamble end
                self.pcm_buffer = self.pcm_buffer[peak_idx + preamble_len :]

                # Initialize demodulation
                self._init_demodulation()

                self.state = DecoderState.LOCKED
                return

        # Keep a sliding window - don't let buffer grow unbounded
        if len(self.pcm_buffer) > preamble_len * 3:
            self.pcm_buffer = self.pcm_buffer[-preamble_len * 2 :]

    def _check_preamble_while_locked(self) -> None:
        """Check for new preamble while locked (for resync)."""
        preamble_len = len(self.preamble_pcm)

        # Need enough buffer to correlate
        if len(self.preamble_check_buffer) < preamble_len:
            return

        # Compute correlation (reuse logic from _search_for_preamble)
        correlation = np.correlate(
            (
                self.preamble_check_buffer[: preamble_len * 2]
                if len(self.preamble_check_buffer) >= preamble_len * 2
                else self.preamble_check_buffer
            ),
            self.preamble_pcm,
            mode="valid",
        )

        if len(correlation) > 0:
            max_corr = np.max(np.abs(correlation))
            preamble_energy = np.linalg.norm(self.preamble_pcm)
            norm_corr = max_corr / (preamble_energy * np.sqrt(preamble_len))

            # If strong correlation detected, resync
            if norm_corr > self.preamble_correlation_threshold:
                peak_idx = np.argmax(np.abs(correlation))

                # Clear session state for clean resync
                self.bit_buffer = []
                self.packet_queue.clear()

                # Align pcm_buffer to new preamble
                # The preamble was detected in preamble_check_buffer at peak_idx
                # We need to clear pcm_buffer and start fresh after the preamble
                self.pcm_buffer = self.preamble_check_buffer[peak_idx + preamble_len :]

                # Clear preamble check buffer
                self.preamble_check_buffer = np.array([], dtype=np.float64)

                # Re-initialize demodulation
                self._init_demodulation()
                # Stay in LOCKED state

        # Keep preamble check buffer from growing too large
        if len(self.preamble_check_buffer) > preamble_len * 2:
            self.preamble_check_buffer = self.preamble_check_buffer[-preamble_len:]

    def _init_demodulation(self) -> None:
        """Initialize demodulation components."""
        # Don't consume the buffer yet - keep it for demodulation
        # Create a generator that will yield from buffer as we process
        self.modem = amodem.dsp.MODEM(self.config.symbols)
        self.stats["consecutive_errors"] = 0

    def _demodulate_locked(self) -> None:
        """Demodulate symbols and extract frames when locked."""
        if self.modem is None:
            return

        # Need enough samples to process
        if len(self.pcm_buffer) < self.config.Nsym:
            return

        try:
            # Create fresh sampler and demux for this batch
            sampler = amodem.sampling.Sampler(iter(self.pcm_buffer))
            omegas = 2 * np.pi * np.array(self.config.frequencies) / self.config.Fs
            symbols_iter = amodem.dsp.Demux(sampler=sampler, omegas=omegas, Nsym=self.config.Nsym)

            # Process ALL available symbols
            symbols_processed = 0
            for symbol_vector in symbols_iter:
                symbols_processed += 1

                # Decode each carrier frequency
                for symbol in symbol_vector:
                    # Find closest constellation point
                    distances = np.abs(self.modem.symbols - symbol)
                    closest_idx = np.argmin(distances)

                    # Convert index to bits
                    bits: list[int] = []
                    idx = int(closest_idx)
                    for _ in range(self.modem.bits_per_symbol):
                        bits.append(int(idx & 1))
                        idx >>= 1

                    self.bit_buffer.extend(bits)

            # Try to extract frames after processing all symbols
            if len(self.bit_buffer) >= 48:
                self._extract_frames()

            # Consume processed samples from buffer
            samples_consumed = symbols_processed * self.config.Nsym
            if samples_consumed > 0 and samples_consumed <= len(self.pcm_buffer):
                self.pcm_buffer = self.pcm_buffer[samples_consumed:]
            else:
                # Consumed everything or more
                self.pcm_buffer = np.array([], dtype=np.float64)

        except Exception:
            # If demodulation fails, increment error counter
            self.stats["consecutive_errors"] += 1

            # If too many consecutive errors, drop lock
            if self.stats["consecutive_errors"] >= self.crc_error_threshold:
                self.state = DecoderState.SEARCH_PREAMBLE
                self.modem = None
                self.bit_buffer = []

    def _extract_frames(self) -> None:
        """Try to extract frames from bit buffer.

        For streaming, we manually parse frames and group them into packets.
        Each packet consists of data frames followed by an EOF frame.
        We continue past EOF to extract multiple packets from the stream.
        """
        # Need at least minimum frame size (1 byte length + 4 bytes CRC)
        if len(self.bit_buffer) < 40:  # 5 bytes = 40 bits
            return

        # Convert bits to bytes for easier parsing
        # Only convert complete bytes (multiples of 8 bits)
        num_complete_bytes = len(self.bit_buffer) // 8
        if num_complete_bytes < 5:
            return

        byte_buffer = []
        for i in range(num_complete_bytes):
            byte_bits = self.bit_buffer[i * 8 : (i + 1) * 8]
            byte_val = sum(b << j for j, b in enumerate(byte_bits))
            byte_buffer.append(byte_val)

        framer = amodem.framing.Framer()
        checksum = framer.checksum
        bytes_consumed = 0

        # Keep extracting packets until we run out of data
        for _ in range(self.frame_extraction_limit):
            if bytes_consumed >= len(byte_buffer):
                break

            try:
                # Read frame header (length byte)
                length_byte = byte_buffer[bytes_consumed]
                bytes_consumed += 1

                # Check if we have enough bytes for the frame
                if bytes_consumed + length_byte > len(byte_buffer):
                    # Not enough data, rewind and wait for more
                    bytes_consumed -= 1
                    break

                # Read frame data (CRC + payload)
                frame_data = bytes(byte_buffer[bytes_consumed : bytes_consumed + length_byte])
                bytes_consumed += length_byte

                # Decode frame (verify CRC)
                try:
                    payload = checksum.decode(frame_data)

                    # Check if this is EOF frame
                    if payload == framer.EOF:
                        # EOF found - packet complete, continue to look for next packet
                        self.stats["consecutive_errors"] = 0
                        pass  # Continue to next frame/packet
                    else:
                        # Data frame - add to queue
                        self.packet_queue.append(payload)
                        self.stats["consecutive_errors"] = 0

                except ValueError:
                    # CRC error
                    self.stats["crc_errors"] += 1

                    # If too many errors, try to resync
                    if len(self.bit_buffer) > self.bit_buffer_resync_threshold:
                        self.stats["consecutive_errors"] += 1
                        if self.stats["consecutive_errors"] >= self.crc_error_threshold:
                            self.state = DecoderState.SEARCH_PREAMBLE
                            self.bit_buffer = []
                            return
                    break

            except (IndexError, struct.error):
                # Not enough data
                break

        # Remove consumed bits from buffer
        bits_consumed = bytes_consumed * 8
        if bits_consumed > 0:
            self.bit_buffer = self.bit_buffer[bits_consumed:]

    def get_packet(self) -> bytes | None:
        """Extract a decoded packet if available.

        Returns:
            Decoded packet bytes, or None if no packet available
        """
        if self.packet_queue:
            return self.packet_queue.popleft()
        return None

    def get_state(self) -> DecoderState:
        """Get the current decoder state.

        Returns:
            Current state (SEARCH_PREAMBLE or LOCKED)
        """
        return self.state

    def get_stats(self) -> dict[str, float]:
        """Get decoder statistics.

        Returns:
            Dictionary with keys: correlation, crc_errors, consecutive_errors, snr
        """
        return self.stats.copy()

    def is_heartbeat(self, packet: bytes) -> bool:
        """Check if a packet is a heartbeat packet.

        Args:
            packet: Packet bytes to check

        Returns:
            True if packet is a heartbeat, False otherwise
        """
        return packet == encoder.HEARTBEAT_MARKER
