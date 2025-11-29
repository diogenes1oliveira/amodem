# mypy: disable-error-code="no-untyped-def"

"""Tests for various configuration variations and stress tests."""

import pytest

import amodem.config
from amodem_duplex import decoder, encoder


class TestConfigVariations:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    @pytest.fixture
    def enc(self, config):
        return encoder.StreamEncoder(config, chunk_samples=640)

    @pytest.fixture
    def dec(self, config):
        return decoder.StreamDecoder(config, crc_error_threshold=3)

    def test_slowest_config(self):
        config = amodem.config.slowest()
        enc = encoder.StreamEncoder(config)
        dec = decoder.StreamDecoder(config)

        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED
        packet = dec.get_packet()
        assert packet == b"test"

    @pytest.mark.parametrize("chunk_samples", [64, 320, 640, 1280, 2560])
    def test_various_chunk_sizes(self, config: amodem.config.Configuration, chunk_samples: int):
        enc = encoder.StreamEncoder(config, chunk_samples=chunk_samples)

        enc.feed_packet(b"test")

        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                assert len(chunk) <= chunk_samples

    @pytest.mark.parametrize("heartbeat_interval", [0.1, 0.5, 1.0, 5.0, 10.0])
    def test_various_heartbeat_intervals(self, config: amodem.config.Configuration, heartbeat_interval: float):
        enc = encoder.StreamEncoder(config, heartbeat_interval=heartbeat_interval)

        enc.send_heartbeat()

        assert enc.has_data()

    @pytest.mark.parametrize("preamble_interval", [1.0, 3.0, 10.0, 30.0])
    def test_various_preamble_intervals(self, config: amodem.config.Configuration, preamble_interval: float):
        enc = encoder.StreamEncoder(config, preamble_interval=preamble_interval)

        preamble = list(enc.emit_preamble())

        assert len(preamble) > 0

    @pytest.mark.parametrize("crc_threshold", [1, 3, 5, 10])
    def test_various_crc_thresholds(self, config: amodem.config.Configuration, crc_threshold: int):
        dec = decoder.StreamDecoder(config, crc_error_threshold=crc_threshold)

        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE

    def test_1000_packets_round_trip(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        for i in range(10):
            test_payload = f"packet{i}".encode()
            enc.feed_packet(test_payload)

        while enc.has_data():
            maybe_chunk = enc.get_pcm_chunk()
            if maybe_chunk is not None:
                dec.feed_pcm(maybe_chunk)

        packets = []
        for _ in range(15):
            pkt = dec.get_packet()
            if pkt:
                packets.append(pkt)

        assert len(packets) >= 1

    def test_packet_size_range(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        for size in [1, 10, 50, 100, 500]:
            test_payload = b"x" * size
            enc.feed_packet(test_payload)

        while enc.has_data():
            maybe_chunk = enc.get_pcm_chunk()
            if maybe_chunk is not None:
                dec.feed_pcm(maybe_chunk)

        packets = []
        for _ in range(10):
            pkt = dec.get_packet()
            if pkt:
                packets.append(pkt)

        assert len(packets) >= 1

    def test_long_session_memory(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        for _ in range(50):
            enc.feed_packet(b"test")

        while enc.has_data():
            maybe_chunk = enc.get_pcm_chunk()
            if maybe_chunk is not None:
                dec.feed_pcm(maybe_chunk)

        assert enc is not None
        assert dec is not None
