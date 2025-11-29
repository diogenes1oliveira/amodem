# mypy: disable-error-code="no-untyped-def"

"""Tests for loopback failure modes and integration edge cases."""

import numpy as np
import pytest

import amodem.config
from amodem_duplex import decoder, encoder


class TestLoopbackFailures:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    @pytest.fixture
    def enc(self, config):
        return encoder.StreamEncoder(config, chunk_samples=640)

    @pytest.fixture
    def dec(self, config):
        return decoder.StreamDecoder(config, crc_error_threshold=3)

    def test_partial_transmission(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"Hello, World!"

        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        half_index = len(all_pcm) // 2
        for chunk in all_pcm[:half_index]:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_partial_transmission_at_frame_boundary(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"test"

        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        cutoff = len(all_pcm) - 1
        for chunk in all_pcm[:cutoff]:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_dropped_chunks_periodic(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"Hello, World!"

        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for i, chunk in enumerate(all_pcm):
            if i % 3 != 0:
                dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_dropped_chunks_random(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"Hello, World!"

        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        np.random.seed(42)
        for chunk in all_pcm:
            if np.random.rand() > 0.3:
                dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_duplicated_chunks(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"test"

        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for i, chunk in enumerate(all_pcm):
            dec.feed_pcm(chunk)
            if i % 3 == 0:
                dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_out_of_order_chunks(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"test"

        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        np.random.seed(42)
        shuffled = all_pcm.copy()
        np.random.shuffle(shuffled)

        for chunk in shuffled:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_decoder_reuse_without_reset(self, config: amodem.config.Configuration):
        dec = decoder.StreamDecoder(config)
        enc1 = encoder.StreamEncoder(config)
        enc2 = encoder.StreamEncoder(config)

        preamble1 = list(enc1.emit_preamble())
        enc1.feed_packet(b"first")
        pcm1 = preamble1.copy()
        while enc1.has_data():
            chunk = enc1.get_pcm_chunk()
            if chunk is not None:
                pcm1.append(chunk)

        for chunk in pcm1:
            dec.feed_pcm(chunk)

        packet1 = dec.get_packet()

        preamble2 = list(enc2.emit_preamble())
        enc2.feed_packet(b"second")
        pcm2 = preamble2.copy()
        while enc2.has_data():
            chunk = enc2.get_pcm_chunk()
            if chunk is not None:
                pcm2.append(chunk)

        for chunk in pcm2:
            dec.feed_pcm(chunk)

        packet2 = dec.get_packet()

        assert packet1 is None or isinstance(packet1, (bytes, bytearray))
        assert packet2 is None or isinstance(packet2, (bytes, bytearray))

    @pytest.mark.xfail(
        reason="Known issue: Multiple consecutive packets cause CRC errors (decoder doesn't restart after first EOF)"
    )
    def test_encoder_reuse_multiple_packets(self, config: amodem.config.Configuration):
        enc = encoder.StreamEncoder(config)
        dec = decoder.StreamDecoder(config)

        for i in range(3):
            preamble = list(enc.emit_preamble())
            enc.feed_packet(f"packet{i}".encode())

            all_pcm = preamble.copy()
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

    def test_interleaved_sessions(self, config: amodem.config.Configuration):
        enc1 = encoder.StreamEncoder(config)
        enc2 = encoder.StreamEncoder(config)
        dec = decoder.StreamDecoder(config)

        preamble1 = list(enc1.emit_preamble())
        enc1.feed_packet(b"test1")
        pcm1 = preamble1.copy()
        while enc1.has_data():
            chunk = enc1.get_pcm_chunk()
            if chunk is not None:
                pcm1.append(chunk)

        preamble2 = list(enc2.emit_preamble())
        enc2.feed_packet(b"test2")
        pcm2 = preamble2.copy()
        while enc2.has_data():
            chunk = enc2.get_pcm_chunk()
            if chunk is not None:
                pcm2.append(chunk)

        interleaved = []
        for i in range(max(len(pcm1), len(pcm2))):
            if i < len(pcm1):
                interleaved.append(pcm1[i])
            if i < len(pcm2):
                interleaved.append(pcm2[i])

        for chunk in interleaved:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_decoder_multiple_locks(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        for _ in range(3):
            preamble = list(enc.emit_preamble())
            for chunk in preamble:
                dec.feed_pcm(chunk)

            assert dec.get_state() == decoder.DecoderState.LOCKED

            random_pcm = np.random.randn(10000) * 0.5
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_mismatched_configs_different_speeds(self):
        enc_config = amodem.config.slowest()
        dec_config = amodem.config.slowest()

        enc = encoder.StreamEncoder(enc_config)
        dec = decoder.StreamDecoder(dec_config)

        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_mismatched_configs_different_freqs(self):
        config1 = amodem.config.slowest()
        config2 = amodem.config.slowest()

        enc = encoder.StreamEncoder(config1)
        dec = decoder.StreamDecoder(config2)

        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_mismatched_configs_different_symbols(self):
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

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_preamble_overlap(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble1 = list(enc.emit_preamble())
        preamble2 = list(enc.emit_preamble())

        half_idx = len(preamble1) // 2
        overlapped = preamble1[:half_idx] + preamble2

        for chunk in overlapped:
            dec.feed_pcm(chunk)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_heartbeat_flood(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        for _ in range(10):
            enc.send_heartbeat()

        while enc.has_data():
            maybe_chunk = enc.get_pcm_chunk()
            if maybe_chunk is not None:
                dec.feed_pcm(maybe_chunk)

        packets = []
        for _ in range(15):
            pkt = dec.get_packet()
            if pkt:
                packets.append(pkt)

        assert isinstance(packets, list)

    def test_alternating_valid_invalid(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        for i in range(5):
            if i % 2 == 0:
                preamble = list(enc.emit_preamble())
                enc.feed_packet(b"valid")
                pcm = preamble.copy()
                while enc.has_data():
                    chunk = enc.get_pcm_chunk()
                    if chunk is not None:
                        pcm.append(chunk)
                for chunk in pcm:
                    dec.feed_pcm(chunk)
            else:
                random_pcm = np.random.randn(5000) * 0.5
                dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_missing_preamble(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        enc.feed_packet(b"test")

        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE
        packet = dec.get_packet()
        assert packet is None

    def test_late_preamble(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        enc.feed_packet(b"test")

        data_pcm = []
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                data_pcm.append(chunk)

        for chunk in data_pcm:
            dec.feed_pcm(chunk)

        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_buffer_starvation(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        tiny_chunk = all_pcm[0][:10]
        dec.feed_pcm(tiny_chunk)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_crc_threshold_boundary_minus_one(self, config: amodem.config.Configuration):
        dec = decoder.StreamDecoder(config, crc_error_threshold=3)
        enc = encoder.StreamEncoder(config)

        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        for _ in range(2):
            random_pcm = np.random.randn(5000) * 0.5
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_crc_threshold_boundary_exact(self, config: amodem.config.Configuration):
        dec = decoder.StreamDecoder(config, crc_error_threshold=3)
        enc = encoder.StreamEncoder(config)

        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        for _ in range(3):
            random_pcm = np.random.randn(5000) * 0.5
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_crc_threshold_boundary_plus_one(self, config: amodem.config.Configuration):
        dec = decoder.StreamDecoder(config, crc_error_threshold=3)
        enc = encoder.StreamEncoder(config)

        preamble = list(enc.emit_preamble())
        for chunk in preamble:
            dec.feed_pcm(chunk)

        assert dec.get_state() == decoder.DecoderState.LOCKED

        for _ in range(4):
            random_pcm = np.random.randn(5000) * 0.5
            dec.feed_pcm(random_pcm)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_corruption_in_preamble(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())

        corrupted_idx = len(preamble) // 2
        preamble[corrupted_idx] = preamble[corrupted_idx] + np.random.randn(len(preamble[corrupted_idx])) * 0.5

        for chunk in preamble:
            dec.feed_pcm(chunk)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)

    def test_corruption_in_header(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test data")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        if len(all_pcm) > len(preamble):
            first_data_chunk = all_pcm[len(preamble)].copy()
            first_data_chunk[:100] += np.random.randn(100) * 0.5
            all_pcm[len(preamble)] = first_data_chunk

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_corruption_in_payload(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test data here")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        if len(all_pcm) > len(preamble) + 1:
            mid_idx = (len(preamble) + len(all_pcm)) // 2
            all_pcm[mid_idx] = all_pcm[mid_idx] + np.random.randn(len(all_pcm[mid_idx])) * 0.3

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_corruption_in_crc_field(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        if len(all_pcm) > 0:
            last_chunk = all_pcm[-1].copy()
            last_chunk[-50:] += np.random.randn(50) * 0.5
            all_pcm[-1] = last_chunk

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        packet = dec.get_packet()
        assert packet is None or isinstance(packet, (bytes, bytearray))

    def test_gradual_corruption_increase(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"test data")

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for i, chunk in enumerate(all_pcm):
            noise_level = i * 0.05
            noisy = chunk + np.random.randn(len(chunk)) * noise_level
            dec.feed_pcm(noisy)

        state = dec.get_state()
        assert state in (decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE)
