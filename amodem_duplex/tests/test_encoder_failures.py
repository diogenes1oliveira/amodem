# mypy: disable-error-code="no-untyped-def"

"""Tests for encoder failure modes and edge cases."""

import pytest

import amodem.config
from amodem_duplex import encoder


class TestEncoderFailures:
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

    def test_empty_packet(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"")
        result = enc.has_data()

        assert result is False

    def test_feed_packet_with_none(self, enc: encoder.StreamEncoder):
        with pytest.raises(TypeError):
            enc.feed_packet(None)

    def test_feed_packet_with_string(self, enc: encoder.StreamEncoder):
        with pytest.raises(TypeError):
            enc.feed_packet("test")

    def test_feed_packet_with_int(self, enc: encoder.StreamEncoder):
        with pytest.raises(TypeError):
            enc.feed_packet(42)

    def test_rapid_feed_without_draining(self, enc: encoder.StreamEncoder):
        for _ in range(100):
            enc.feed_packet(b"test" + str(i).encode())

        assert enc.has_data()
        chunks_count = 0
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                chunks_count += 1

        assert chunks_count > 0

    def test_bit_buffer_partial_symbols(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"X")

        pcm_chunk = enc.get_pcm_chunk()

        assert pcm_chunk is not None
        assert len(pcm_chunk) > 0

    def test_pcm_buffer_fragmentation(self, enc: encoder.StreamEncoder):
        for _ in range(50):
            enc.feed_packet(b"x")

        chunk_count = 0
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                chunk_count += 1

        assert chunk_count > 0

    def test_multiple_preamble_emissions(self, enc: encoder.StreamEncoder):
        chunks1 = list(enc.emit_preamble())
        chunks2 = list(enc.emit_preamble())
        chunks3 = list(enc.emit_preamble())

        assert len(chunks1) > 0
        assert len(chunks2) > 0
        assert len(chunks3) > 0

    @pytest.mark.xfail(reason="Bug: IndexError when chunk_samples=0, should return None gracefully")
    def test_zero_chunk_samples(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, chunk_samples=0, clock_func=mock_clock)

        enc.feed_packet(b"test")
        chunk = enc.get_pcm_chunk()

        assert chunk is None or len(chunk) == 0

    @pytest.mark.xfail(reason="Bug: IndexError when chunk_samples<0, should return None gracefully")
    def test_negative_chunk_samples(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, chunk_samples=-100, clock_func=mock_clock)

        enc.feed_packet(b"test")
        chunk = enc.get_pcm_chunk()

        assert chunk is None or len(chunk) == 0

    def test_zero_heartbeat_interval(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, heartbeat_interval=0.0, clock_func=mock_clock)

        needs_hb = enc.needs_heartbeat()

        assert isinstance(needs_hb, bool)

    def test_negative_preamble_interval(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, preamble_interval=-5.0, clock_func=mock_clock)

        needs_pre = enc.needs_preamble()

        assert isinstance(needs_pre, bool)

    def test_clock_jumping_forward(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, heartbeat_interval=1.0, preamble_interval=3.0, clock_func=mock_clock)

        mock_clock.advance(1000.0)
        needs_hb = enc.needs_heartbeat()
        needs_pre = enc.needs_preamble()

        assert isinstance(needs_hb, bool)
        assert isinstance(needs_pre, bool)

    def test_heartbeat_spam(self, enc: encoder.StreamEncoder, mock_clock):
        for _ in range(100):
            enc.send_heartbeat()

        assert enc.has_data()

    def test_needs_preamble_at_exact_interval(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, preamble_interval=3.0, clock_func=mock_clock)

        list(enc.emit_preamble())
        mock_clock.advance(3.0)
        needs_pre = enc.needs_preamble()

        assert needs_pre is True

    def test_needs_heartbeat_at_exact_interval(self, config: amodem.config.Configuration, mock_clock):
        enc = encoder.StreamEncoder(config, heartbeat_interval=1.0, clock_func=mock_clock)

        enc.send_heartbeat()
        while enc.has_data():
            enc.get_pcm_chunk()

        mock_clock.advance(1.0)
        needs_hb = enc.needs_heartbeat()

        assert needs_hb is True

    def test_preamble_emission_while_data_queued(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"test")

        preamble_chunks = list(enc.emit_preamble())

        assert len(preamble_chunks) > 0
        assert enc.has_data()

    def test_get_pcm_chunk_exhaustive_drain(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"test")

        chunks = []
        for _ in range(1000):
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                chunks.append(chunk)
            if not enc.has_data():
                break

        assert len(chunks) > 0
        assert not enc.has_data()

    def test_has_data_after_partial_chunk(self, enc: encoder.StreamEncoder):
        enc.feed_packet(b"X")

        has_data_before = enc.has_data()
        chunk = enc.get_pcm_chunk()
        has_data_after = enc.has_data()

        assert has_data_before is True
        assert chunk is not None
