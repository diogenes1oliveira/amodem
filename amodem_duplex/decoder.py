"""Stream decoder for sans-I/O packet decoding with state machine."""

import collections
import enum
from typing import Deque, Dict, List, Optional

import numpy as np
import numpy.typing as npt

import amodem.config
import amodem.detect
import amodem.dsp
import amodem.equalizer
import amodem.framing
import amodem.sampling
from amodem_duplex import encoder, preamble


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

    def __init__(self, config: amodem.config.Configuration, crc_error_threshold: int = 3) -> None:
        """Initialize the stream decoder.

        Args:
            config: amodem configuration object
            crc_error_threshold: Number of consecutive CRC failures before dropping lock
        """
        self.config = config
        self.crc_error_threshold = crc_error_threshold

        # State
        self.state = DecoderState.SEARCH_PREAMBLE

        # PCM buffer
        self.pcm_buffer: npt.NDArray[np.float64] = np.array([], dtype=np.float64)

        # Packet queue (decoded packets waiting to be retrieved)
        self.packet_queue: Deque[bytes] = collections.deque()

        # Bit buffer (for frame extraction)
        self.bit_buffer: List[int] = []

        # Framer for packet decoding
        self.framer = amodem.framing.Framer()

        # Stats tracking
        self.stats = {
            "correlation": 0.0,
            "crc_errors": 0,
            "consecutive_errors": 0,
            "snr": 0.0,
        }

        # Demodulation components (created when locked)
        self.modem: Optional[amodem.dsp.MODEM] = None

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
            if norm_corr > 0.3:  # Threshold (tunable)
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
                    bits: List[int] = []
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
        """Try to extract frames from bit buffer."""
        # Need at least enough bits for frame header (1 byte length + 4 byte CRC + data)
        # Minimum frame is about 5-6 bytes = 40-48 bits
        if len(self.bit_buffer) < 48:
            return

        try:
            # Convert bits to bytes iterator
            # framing._to_bytes expects an iterator of bits and yields byte lists
            bits_copy = self.bit_buffer.copy()
            bytes_iter = amodem.framing._to_bytes(iter(bits_copy))

            # Try to decode frames
            packets_decoded = 0

            for frame in self.framer.decode(bytes_iter):
                self.packet_queue.append(frame)
                self.stats["consecutive_errors"] = 0  # Reset on success
                packets_decoded += 1

            # If we successfully decoded, clear the bit buffer
            if packets_decoded > 0:
                self.bit_buffer = []

        except ValueError:
            # CRC error or incomplete frame
            self.stats["crc_errors"] += 1
            # Don't increment consecutive_errors here - only do that on repeated failures
            # without any successful decodes in between

            # Don't clear buffer - might just need more bits
            # But if we have too many bits without success, try shifting
            if len(self.bit_buffer) > 4000:
                # Drop some bits and try to resync
                self.bit_buffer = self.bit_buffer[800:]
                self.stats["consecutive_errors"] += 1

                # Check if we should drop lock
                if self.stats["consecutive_errors"] >= self.crc_error_threshold:
                    self.state = DecoderState.SEARCH_PREAMBLE

        except StopIteration:
            # Not enough data yet, keep accumulating
            pass

    def get_packet(self) -> Optional[bytes]:
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

    def get_stats(self) -> Dict[str, float]:
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
