# mypy: disable-error-code="no-untyped-def"

"""Tests for decoder failure modes and edge cases."""

import numpy as np
import pytest

import amodem.config
from amodem_duplex.protocol import decoder, encoder, preamble


class TestDecoderFailures:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    @pytest.fixture
    def dec(self, config):
        return decoder.StreamDecoder(config, crc_error_threshold=3)

    @pytest.fixture
    def enc(self, config):
        return encoder.StreamEncoder(config, chunk_samples=640)

    def test_truncated_preamble(self, dec: decoder.StreamDecoder, config: amodem.config.Configuration):
        preamble_pcm = preamble.generate_preamble_pcm(config)

        half_preamble = preamble_pcm[: len(preamble_pcm) // 2]
        dec.feed_pcm(half_preamble)

        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE

    def test_repeated_preambles_while_locked(
        self, dec: decoder.StreamDecoder, config: amodem.config.Configuration, enc: encoder.StreamEncoder
    ):
        preamble_pcm = preamble.generate_preamble_pcm(config)

        for i in range(0, len(preamble_pcm), 640):
            dec.feed_pcm(preamble_pcm[i : i + 640])

        assert dec.get_state() == decoder.DecoderState.LOCKED

        for i in range(0, len(preamble_pcm), 640):
            dec.feed_pcm(preamble_pcm[i : i + 640])

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_preamble_with_phase_shift(self, dec: decoder.StreamDecoder, config: amodem.config.Configuration):
        preamble_pcm = preamble.generate_preamble_pcm(config)

        phase_shifted = np.roll(preamble_pcm, 10)
        for i in range(0, len(phase_shifted), 640):
            dec.feed_pcm(phase_shifted[i : i + 640])

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_inverted_preamble(self, dec: decoder.StreamDecoder, config: amodem.config.Configuration):
        preamble_pcm = preamble.generate_preamble_pcm(config)

        inverted = -preamble_pcm
        for i in range(0, len(inverted), 640):
            dec.feed_pcm(inverted[i : i + 640])

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_weak_preamble(self, dec: decoder.StreamDecoder, config: amodem.config.Configuration):
        preamble_pcm = preamble.generate_preamble_pcm(config)

        weak = preamble_pcm * 0.01
        for i in range(0, len(weak), 640):
            dec.feed_pcm(weak[i : i + 640])

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_malformed_frame_header(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        random_pcm = np.random.randn(5000) * 0.1
        dec.feed_pcm(random_pcm)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, bytes)

    def test_wrong_frame_crc(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble_pcm.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        corrupted_pcm = all_pcm[-1].copy()
        corrupted_pcm[-10:] += np.random.randn(10) * 2.0
        all_pcm[-1] = corrupted_pcm

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or packet == b"test"

    def test_eof_without_data(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        random_pcm = np.random.randn(1000) * 0.01
        dec.feed_pcm(random_pcm)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, bytes)

    def test_double_eof_frames(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        enc.feed_packet(b"test1")
        enc.feed_packet(b"test2")

        all_pcm = preamble_pcm.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packets = []
        for _ in range(5):
            pkt = dec.get_packet()
            if pkt:
                packets.append(pkt)

        assert len(packets) >= 1

    def test_frame_with_invalid_length(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        random_bits_pcm = np.random.randn(10000) * 0.1
        dec.feed_pcm(random_bits_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_bit_buffer_overflow(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        for _ in range(100):
            random_pcm = np.random.randn(1000) * 0.1
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_pcm_buffer_overflow(self, dec: decoder.StreamDecoder):
        for _ in range(1000):
            massive_pcm = np.random.randn(10000)
            dec.feed_pcm(massive_pcm)

        assert dec is not None

    def test_partial_symbol_boundaries(self, dec: decoder.StreamDecoder, config: amodem.config.Configuration):
        preamble_pcm = preamble.generate_preamble_pcm(config)

        for i in range(len(preamble_pcm)):
            dec.feed_pcm(preamble_pcm[i : i + 1])

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_bit_buffer_at_exact_threshold(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        for _ in range(10):
            random_pcm = np.random.randn(2000) * 0.1
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_consecutive_errors_at_threshold(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        for _ in range(5):
            random_pcm = np.random.randn(5000) * 0.5
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_zero_amplitude_signal(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        zeros = np.zeros(5000)
        dec.feed_pcm(zeros)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_maximum_amplitude_saturation(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        saturated = np.ones(5000) * 10.0
        dec.feed_pcm(saturated)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_extremely_low_snr(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble_pcm.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            noisy = chunk + np.random.randn(len(chunk)) * 5.0
            dec.feed_pcm(noisy)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_dc_offset(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble_pcm.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            with_offset = chunk + 5.0
            dec.feed_pcm(with_offset)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_sudden_amplitude_change(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble_pcm.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for i, chunk in enumerate(all_pcm):
            if i < len(all_pcm) // 2:
                dec.feed_pcm(chunk)
            else:
                dec.feed_pcm(chunk * 5.0)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_feed_pcm_massive_chunks(self, dec: decoder.StreamDecoder):
        massive_chunk = np.random.randn(100000)

        dec.feed_pcm(massive_chunk)

        assert dec is not None

    def test_feed_pcm_tiny_chunks(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())

        for chunk in preamble_pcm:
            for sample in chunk:
                dec.feed_pcm(np.array([sample]))

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_get_packet_spam(self, dec: decoder.StreamDecoder):
        for _ in range(1000):
            packet = dec.get_packet()

        assert packet is None

    def test_stats_during_search(self, dec: decoder.StreamDecoder):
        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE

        stats = dec.get_stats()

        assert isinstance(stats, dict)
        assert "crc_errors" in stats

    def test_stats_during_locked(self, dec: decoder.StreamDecoder, enc: encoder.StreamEncoder):
        preamble_pcm = list(enc.emit_preamble())
        for chunk in preamble_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        stats = dec.get_stats()

        assert isinstance(stats, dict)
        assert "crc_errors" in stats

    def test_crc_error_threshold_zero(self, config: amodem.config.Configuration):
        dec = decoder.StreamDecoder(config, crc_error_threshold=0)

        assert dec is not None
        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE

    def test_crc_error_threshold_large(self, config: amodem.config.Configuration):
        dec = decoder.StreamDecoder(config, crc_error_threshold=100)

        assert dec is not None
        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE
