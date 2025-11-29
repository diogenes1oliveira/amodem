"""Stream encoder for sans-I/O packet encoding with heartbeat."""

import collections
import time
from typing import Callable, Deque, Iterator, List, Optional

import numpy as np
import numpy.typing as npt

import amodem.config
import amodem.dsp
import amodem.framing
from amodem_duplex import preamble

# Heartbeat marker bytes
HEARTBEAT_MARKER = b"\x00\x00HEARTBEAT\x00\x00"


class StreamEncoder:
    """Sans-I/O encoder that converts packets to PCM chunks with periodic preambles and heartbeats.

    This encoder:
    - Accepts packets via feed_packet()
    - Generates fixed-size PCM chunks via get_pcm_chunk()
    - Emits preambles periodically for decoder synchronization
    - Sends heartbeat packets when idle to keep the channel active
    - Uses injectable clock function for testing
    """

    def __init__(
        self,
        config: amodem.config.Configuration,
        chunk_samples: int = 640,
        heartbeat_interval: float = 1.0,
        preamble_interval: float = 3.0,
        clock_func: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the stream encoder.

        Args:
            config: amodem configuration object (determines sample rate, etc.)
            chunk_samples: Number of samples per PCM chunk (default 640 @ 16kHz = 40ms)
            heartbeat_interval: Seconds between heartbeats when idle (default 1.0)
            preamble_interval: Seconds between preambles during transmission (default 3.0)
            clock_func: Clock function for time tracking (default time.monotonic, mockable for tests)
        """
        self.config = config
        self.chunk_samples = chunk_samples
        self.heartbeat_interval = heartbeat_interval
        self.preamble_interval = preamble_interval
        self.clock_func = clock_func

        # Packet queue
        self.packet_queue: Deque[bytes] = collections.deque()

        # PCM buffer for output chunks - using deque of arrays for efficient appending
        self.pcm_chunks: Deque[npt.NDArray[np.float64]] = collections.deque()
        self.pcm_buffer_len: int = 0  # Track total samples without concatenating

        # Bit stream buffer (bits waiting to be modulated)
        self.bit_buffer: List[int] = []

        # Framer for packet encoding
        self.framer = amodem.framing.Framer()

        # Timing tracking
        self.last_preamble_time = self.clock_func()
        self.last_transmission_time = self.clock_func()

        # Modulation state
        self.carriers = config.carriers / config.Nfreq
        self.bit_packer = amodem.framing.BitPacker()

        # Symbol encoder
        self.modem = amodem.dsp.MODEM(config.symbols)

    def emit_preamble(self) -> Iterator[npt.NDArray[np.float64]]:
        """Yield PCM chunks for the preamble sequence.

        Yields:
            Fixed-size PCM chunks (numpy arrays) containing the preamble
        """
        # Generate full preamble
        preamble_pcm = preamble.generate_preamble_pcm(self.config)

        # Update preamble timing
        self.last_preamble_time = self.clock_func()

        # Chunk it into fixed-size pieces
        # Note: Last chunk may be shorter than chunk_samples
        for i in range(0, len(preamble_pcm), self.chunk_samples):
            chunk = preamble_pcm[i : i + self.chunk_samples]
            yield chunk

    def feed_packet(self, payload: bytes) -> None:
        """Queue a packet for encoding and transmission.

        Args:
            payload: Raw packet bytes to encode and transmit
        """
        self.packet_queue.append(payload)
        self._process_packets()

    def _process_packets(self) -> None:
        """Process queued packets into bit stream."""
        while self.packet_queue:
            packet = self.packet_queue.popleft()

            # Encode packet to bits using framing module
            # framing.encode expects an iterator of individual bytes
            bits_iter = amodem.framing.encode(iter(packet), framer=self.framer)

            # Add bits to buffer
            for bit in bits_iter:
                self.bit_buffer.append(bit)

        # Modulate bits to PCM
        self._modulate_bits()

    def _modulate_bits(self) -> None:
        """Modulate buffered bits into PCM samples."""
        if not self.bit_buffer:
            return

        # Group bits into symbols
        Nfreq = len(self.carriers)
        bits_per_symbol = self.modem.bits_per_symbol
        bits_per_frame = bits_per_symbol * Nfreq

        while len(self.bit_buffer) >= bits_per_frame:
            # Extract one frame worth of bits
            frame_bits = self.bit_buffer[:bits_per_frame]
            self.bit_buffer = self.bit_buffer[bits_per_frame:]

            # Encode bits to symbols
            symbols_list: List[complex] = []
            for i in range(0, len(frame_bits), bits_per_symbol):
                symbol_bits = tuple(frame_bits[i : i + bits_per_symbol])
                symbol = self.modem.encode_map[symbol_bits]
                symbols_list.append(symbol)

            # Modulate symbols to PCM (one OFDM symbol)
            symbols = np.array(symbols_list)
            pcm_samples = np.dot(symbols, self.carriers).real

            # Add to PCM buffer (efficient - no copying!)
            self.pcm_chunks.append(pcm_samples)
            self.pcm_buffer_len += len(pcm_samples)

    def get_pcm_chunk(self, flush: bool = False) -> Optional[npt.NDArray[np.float64]]:
        """Get the next PCM chunk to transmit.

        Automatically returns partial chunks (< chunk_samples) when there are no
        more packets queued and no more bits to process, making the API more
        convenient for streaming use cases.

        Args:
            flush: If True, force return any remaining samples even if more data
                   might be coming. Used for explicit end-of-transmission.

        Returns:
            PCM chunk as numpy array, or None if no data available
        """
        # Process any remaining packets
        self._process_packets()

        if self.pcm_buffer_len == 0:
            return None

        # Determine if we should auto-flush PARTIAL chunks
        # Auto-flush only applies when buffer < chunk_samples
        no_more_data_coming = len(self.packet_queue) == 0 and len(self.bit_buffer) == 0
        should_auto_flush = no_more_data_coming and self.pcm_buffer_len > 0 and self.pcm_buffer_len < self.chunk_samples

        # Check if we have enough samples for a full chunk
        if not flush and not should_auto_flush and self.pcm_buffer_len < self.chunk_samples:
            return None

        # Determine target samples
        # For full chunks or explicit flush, return all available
        # For partial auto-flush, return what's available
        if flush or should_auto_flush:
            target_samples = self.pcm_buffer_len
        else:
            target_samples = self.chunk_samples

        # Collect chunks until we have enough samples
        chunks_to_concat: List[npt.NDArray[np.float64]] = []
        samples_collected = 0

        while self.pcm_chunks and samples_collected < target_samples:
            chunk = self.pcm_chunks[0]
            needed = target_samples - samples_collected

            if len(chunk) <= needed:
                # Take the whole chunk
                chunks_to_concat.append(chunk)
                samples_collected += len(chunk)
                self.pcm_chunks.popleft()
                self.pcm_buffer_len -= len(chunk)
            else:
                # Take part of the chunk and leave the rest
                chunks_to_concat.append(chunk[:needed])
                self.pcm_chunks[0] = chunk[needed:]
                samples_collected += needed
                self.pcm_buffer_len -= needed

        # Concatenate collected chunks
        result = np.concatenate(chunks_to_concat) if len(chunks_to_concat) > 1 else chunks_to_concat[0]

        # Update transmission time
        self.last_transmission_time = self.clock_func()

        return result

    def has_data(self) -> bool:
        """Check if there is data available to transmit.

        Returns True when either:
        - There are >= chunk_samples available, OR
        - There are any samples available and no more data is coming

        Returns:
            True if get_pcm_chunk() will return data, False otherwise
        """
        # Process any remaining packets
        self._process_packets()

        # Return True if we have a full chunk
        if self.pcm_buffer_len >= self.chunk_samples:
            return True

        # Return True if we have partial data and nothing more is coming
        no_more_data_coming = len(self.packet_queue) == 0 and len(self.bit_buffer) == 0
        return no_more_data_coming and self.pcm_buffer_len > 0

    def needs_preamble(self) -> bool:
        """Check if a preamble should be sent based on elapsed time.

        Uses internal clock tracking to determine if preamble_interval has elapsed
        since the last preamble.

        Returns:
            True if preamble should be sent, False otherwise
        """
        elapsed = self.clock_func() - self.last_preamble_time
        return elapsed >= self.preamble_interval

    def needs_heartbeat(self) -> bool:
        """Check if a heartbeat should be sent based on elapsed time.

        Uses internal clock tracking to determine if heartbeat_interval has elapsed
        since the last data transmission.

        Returns:
            True if heartbeat should be sent, False otherwise
        """
        elapsed = self.clock_func() - self.last_transmission_time
        return elapsed >= self.heartbeat_interval

    def send_heartbeat(self) -> None:
        """Queue a heartbeat packet for transmission.

        Heartbeat packet contains marker bytes: b'\\x00\\x00HEARTBEAT\\x00\\x00'
        This is separate from preambles - both can be sent independently.
        """
        self.feed_packet(HEARTBEAT_MARKER)
        # Update transmission time since we're queuing data
        self.last_transmission_time = self.clock_func()
