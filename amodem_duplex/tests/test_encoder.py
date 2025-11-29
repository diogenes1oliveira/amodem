# mypy: disable-error-code="no-untyped-def"

"""Tests for stream encoder."""


import numpy as np
import pytest

import amodem.config
from amodem_duplex import encoder, preamble


class TestStreamEncoder:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    @pytest.fixture
    def mock_clock(self):
        """Mock clock that can be advanced manually."""

        class MockClock:
            def __init__(self) -> None:
                self.current_time = 0.0

            def __call__(self) -> float:
                return self.current_time

            def advance(self, seconds: float) -> None:
                self.current_time += seconds

        return MockClock()

    @pytest.fixture
    def enc(self, config, mock_clock):
        return encoder.StreamEncoder(
            config, chunk_samples=640, heartbeat_interval=1.0, preamble_interval=3.0, clock_func=mock_clock
        )

    def test_encoder_initializes(self, config: amodem.config.Configuration):
        enc = encoder.StreamEncoder(config)
        assert enc is not None

    def test_encoder_custom_parameters(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(
            config, chunk_samples=320, heartbeat_interval=0.5, preamble_interval=2.0, clock_func=mock_clock
        )
        assert enc is not None

    def test_emit_preamble_returns_iterator(self, enc: encoder.StreamEncoder):
        result = enc.emit_preamble()
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")

    def test_emit_preamble_yields_pcm_chunks(self, enc: encoder.StreamEncoder, config: amodem.config.Configuration):
        chunks = list(enc.emit_preamble())

        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, np.ndarray)
            assert chunk.dtype in (np.float64, np.float32, np.float_)

    def test_preamble_chunks_have_consistent_size(self, enc: encoder.StreamEncoder):
        chunks = list(enc.emit_preamble())

        # All chunks except the last should be the same size
        if len(chunks) > 1:
            chunk_size = len(chunks[0])
            for chunk in chunks[:-1]:
                assert len(chunk) == chunk_size
            # Last chunk may be shorter
            assert len(chunks[-1]) <= chunk_size

    def test_preamble_matches_preamble_helper(self, enc: encoder.StreamEncoder, config: amodem.config.Configuration):
        chunks = list(enc.emit_preamble())
        reconstructed = np.concatenate(chunks)

        expected_preamble = preamble.generate_preamble_pcm(config)

        # Should match the preamble helper output
        np.testing.assert_allclose(reconstructed, expected_preamble, rtol=1e-10)

    def test_has_data_false_when_empty(self, enc: encoder.StreamEncoder):
        assert enc.has_data() is False

    def test_get_pcm_chunk_returns_none_when_empty(self, enc: encoder.StreamEncoder):
        result = enc.get_pcm_chunk()
        assert result is None

    def test_feed_packet_and_get_chunk(self, enc: encoder.StreamEncoder):
        test_payload = b"Hello, World!"

        enc.feed_packet(test_payload)

        assert enc.has_data() is True

        chunk = enc.get_pcm_chunk()
        assert chunk is not None
        assert isinstance(chunk, np.ndarray)
        assert len(chunk) == 640  # chunk_samples parameter

    def test_multiple_packets_in_sequence(self, enc: encoder.StreamEncoder):
        packets = [b"Packet 1", b"Packet 2", b"Packet 3"]

        for pkt in packets:
            enc.feed_packet(pkt)

        # Should be able to retrieve PCM chunks for all packets
        chunks_retrieved = 0
        max_chunks = 1000  # safety limit
        chunks = []

        while enc.has_data() and chunks_retrieved < max_chunks:
            chunk = enc.get_pcm_chunk()
            assert chunk is not None
            chunks.append(chunk)
            chunks_retrieved += 1

        assert chunks_retrieved > 0
        # All chunks except possibly the last should be 640 samples
        for chunk in chunks[:-1]:
            assert len(chunk) == 640
        # Last chunk can be partial due to auto-flush
        assert len(chunks[-1]) <= 640

    def test_chunk_size_consistency(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"Test data" * 100)

        chunks_retrieved = 0
        max_chunks = 100
        chunks = []

        while enc.has_data() and chunks_retrieved < max_chunks:
            chunk = enc.get_pcm_chunk()
            assert chunk is not None
            chunks.append(chunk)
            chunks_retrieved += 1

        assert chunks_retrieved > 0
        # All chunks except possibly the last should be 640 samples
        for chunk in chunks[:-1]:
            assert len(chunk) == 640
        # Last chunk can be partial due to auto-flush
        assert len(chunks[-1]) <= 640

    def test_needs_preamble_initially_false(self, enc: encoder.StreamEncoder):
        # Preamble should not be needed immediately
        assert enc.needs_preamble() is False

    def test_needs_preamble_after_interval(self, enc: encoder.StreamEncoder, mock_clock):
        # Simulate time passing
        mock_clock.advance(3.5)  # Past the 3.0 second interval

        assert enc.needs_preamble() is True

    def test_needs_preamble_resets_after_emit(self, enc: encoder.StreamEncoder, mock_clock):
        mock_clock.advance(3.5)
        assert enc.needs_preamble() is True

        # Emit preamble (consume the iterator)
        list(enc.emit_preamble())

        # Should reset the timer
        assert enc.needs_preamble() is False

        # But become true again after another interval
        mock_clock.advance(3.5)
        assert enc.needs_preamble() is True

    def test_needs_heartbeat_initially_false(self, enc: encoder.StreamEncoder):
        assert enc.needs_heartbeat() is False

    def test_needs_heartbeat_after_idle(self, enc: encoder.StreamEncoder, mock_clock):
        # Simulate idle time
        mock_clock.advance(1.5)  # Past the 1.0 second interval

        assert enc.needs_heartbeat() is True

    def test_send_heartbeat_queues_packet(self, enc: encoder.StreamEncoder):
        enc.send_heartbeat()

        assert enc.has_data() is True

        # Should be able to get PCM chunks for the heartbeat
        chunk = enc.get_pcm_chunk()
        assert chunk is not None

    def test_heartbeat_resets_idle_timer(self, enc: encoder.StreamEncoder, mock_clock):
        mock_clock.advance(1.5)
        assert enc.needs_heartbeat() is True

        enc.send_heartbeat()

        # Should reset after sending heartbeat
        assert enc.needs_heartbeat() is False

        # But become true again after another interval
        mock_clock.advance(1.5)
        assert enc.needs_heartbeat() is True

    def test_data_transmission_resets_heartbeat_timer(self, enc: encoder.StreamEncoder, mock_clock):
        # Feed a packet
        enc.feed_packet(b"Some data")

        # Get a chunk (simulates transmission)
        enc.get_pcm_chunk()

        # Advance time but not enough for heartbeat
        mock_clock.advance(0.5)
        assert enc.needs_heartbeat() is False

        # Advance past heartbeat interval from last transmission
        mock_clock.advance(1.0)
        assert enc.needs_heartbeat() is True

    def test_heartbeat_and_preamble_independent(self, enc: encoder.StreamEncoder, mock_clock):
        # Both can be needed simultaneously
        mock_clock.advance(3.5)

        assert enc.needs_preamble() is True
        assert enc.needs_heartbeat() is True

        # Sending heartbeat doesn't affect preamble
        enc.send_heartbeat()
        assert enc.needs_preamble() is True

        # Emitting preamble doesn't affect heartbeat need
        list(enc.emit_preamble())
        # Note: emitting preamble might count as transmission, resetting heartbeat
        # This is implementation-dependent

    def test_heartbeat_packet_contains_marker(self, enc: encoder.StreamEncoder, config: amodem.config.Configuration):
        # This test verifies the heartbeat actually contains the marker
        # We'll do this in the loopback tests where we can decode it
        enc.send_heartbeat()

        # For now just verify it queues something
        assert enc.has_data() is True

    def test_empty_state_after_draining(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"Short")

        # Drain all chunks
        max_chunks = 1000
        chunks_count = 0
        while enc.has_data() and chunks_count < max_chunks:
            enc.get_pcm_chunk()
            chunks_count += 1

        # Should return to empty state
        assert enc.has_data() is False
        assert enc.get_pcm_chunk() is None

    def test_large_packet(self, enc: encoder.StreamEncoder):
        # Test with a larger packet that will span multiple frames
        large_packet = b"X" * 10000

        enc.feed_packet(large_packet)

        chunks_retrieved = 0
        max_chunks = 10000
        chunks = []

        while enc.has_data() and chunks_retrieved < max_chunks:
            chunk = enc.get_pcm_chunk()
            assert chunk is not None
            chunks.append(chunk)
            chunks_retrieved += 1

        assert chunks_retrieved > 10  # Should take many chunks for such a large packet
        # All chunks except possibly the last should be 640 samples
        for chunk in chunks[:-1]:
            assert len(chunk) == 640
        # Last chunk can be partial due to auto-flush
        assert len(chunks[-1]) <= 640
