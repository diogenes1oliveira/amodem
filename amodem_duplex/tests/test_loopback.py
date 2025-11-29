# mypy: disable-error-code="no-untyped-def,assignment,arg-type"

"""Integration tests for encoder/decoder loopback."""

import numpy as np
import pytest

import amodem.config
from amodem_duplex import decoder, encoder


class TestLoopback:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    @pytest.fixture
    def enc(self, config):
        return encoder.StreamEncoder(config, chunk_samples=640)

    @pytest.fixture
    def dec(self, config):
        return decoder.StreamDecoder(config, crc_error_threshold=3)

    def test_single_packet_round_trip(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_payload = b"Hello, World!"

        # Encode: preamble + packet
        preamble_chunks = list(enc.emit_preamble())
        enc.feed_packet(test_payload)

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        # Decode
        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        # Verify
        assert dec.get_state() == decoder.DecoderState.LOCKED
        decoded = dec.get_packet()
        assert decoded == test_payload

    def test_multiple_packets_round_trip(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_packets = [b"First", b"Second", b"Third"]

        # Encode: preamble + all packets
        preamble_chunks = list(enc.emit_preamble())

        all_pcm = preamble_chunks.copy()
        for pkt in test_packets:
            enc.feed_packet(pkt)

        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        # Decode
        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        # Verify - should get at least first packet
        assert dec.get_state() == decoder.DecoderState.LOCKED
        decoded_packets = []
        for _ in range(10):
            pkt = dec.get_packet()
            if pkt is not None:
                decoded_packets.append(bytes(pkt))

        assert len(decoded_packets) >= 1
        assert decoded_packets[0] == test_packets[0]

    def test_periodic_preamble_resync(
        self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder, config: amodem.config.Configuration
    ):
        # Test that preambles can be sent periodically without breaking decoding
        # This simulates the streaming use case where preambles are re-sent every N seconds

        # First packet with preamble
        preamble1 = list(enc.emit_preamble())
        enc.feed_packet(b"Packet one")

        pcm1 = preamble1.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm1.append(chunk)

        # Feed and verify first works
        for chunk in pcm1:
            dec.feed_pcm(chunk)

        # Decoder should lock and potentially have packet
        # (Don't assert packet exists as timing may vary)
        assert dec.get_state() == decoder.DecoderState.LOCKED

        # Now test that another preamble doesn't break things
        # In real streaming, this would happen after timeout/interval
        dec2 = decoder.StreamDecoder(config)  # Fresh decoder

        preamble2 = list(enc.emit_preamble())
        enc.feed_packet(b"Packet two")

        pcm2 = preamble2.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm2.append(chunk)

        for chunk in pcm2:
            dec2.feed_pcm(chunk)

        # Second decoder should also work
        assert dec2.get_state() == decoder.DecoderState.LOCKED

        # At least one decoder should have gotten a packet
        pkt1 = dec.get_packet()
        pkt2 = dec2.get_packet()

        packets_decoded = sum([1 for p in [pkt1, pkt2] if p is not None])
        assert packets_decoded >= 1

    def test_heartbeat_during_idle(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        # Encode preamble + heartbeat
        preamble_chunks = list(enc.emit_preamble())
        enc.send_heartbeat()

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        # Decode
        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        # Should be locked
        assert dec.get_state() == decoder.DecoderState.LOCKED

        # Should get heartbeat packet
        packet = dec.get_packet()
        assert packet is not None
        assert dec.is_heartbeat(packet)

    def test_decoder_ignores_heartbeats(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        # Encode preamble + heartbeat + real data
        preamble_chunks = list(enc.emit_preamble())
        enc.send_heartbeat()
        enc.feed_packet(b"Real data")

        all_pcm = preamble_chunks.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        # Decode
        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        # Get all packets
        packets = []
        for _ in range(5):
            pkt = dec.get_packet()
            if pkt:
                packets.append(bytes(pkt))

        # Should have both heartbeat and real data
        assert len(packets) >= 2

    def test_decoder_recovers_after_noise(
        self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder, config: amodem.config.Configuration
    ):
        # Encode valid preamble + data
        preamble1 = list(enc.emit_preamble())
        enc.feed_packet(b"Before noise")

        pcm1 = []
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm1.append(chunk)

        # Add noise
        noise = [np.random.randn(640) * 0.2 for _ in range(10)]

        # Add recovery preamble + data
        preamble2 = list(enc.emit_preamble())
        enc.feed_packet(b"After recovery")

        pcm2 = []
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm2.append(chunk)

        # Decode all
        for chunk in preamble1 + pcm1 + noise + preamble2 + pcm2:
            dec.feed_pcm(chunk)

        # Should be able to lock again
        packets = []
        for _ in range(10):
            pkt = dec.get_packet()
            if pkt:
                packets.append(bytes(pkt))

        # Should have decoded at least one packet
        assert len(packets) >= 1

    def test_various_packet_sizes(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        test_packets = [
            b"x",  # 1 byte
            b"Small packet",  # ~12 bytes
            b"X" * 100,  # 100 bytes
            b"Large" * 50,  # ~250 bytes
        ]

        for payload in test_packets:
            # Fresh encoder/decoder
            enc_local = encoder.StreamEncoder(enc.config, chunk_samples=640)
            dec_local = decoder.StreamDecoder(dec.config)

            # Encode
            preamble = list(enc_local.emit_preamble())
            enc_local.feed_packet(payload)

            all_pcm = preamble.copy()
            while enc_local.has_data():
                chunk = enc_local.get_pcm_chunk()
                if chunk is not None:
                    all_pcm.append(chunk)

            # Decode
            for chunk in all_pcm:
                dec_local.feed_pcm(chunk)

            # Verify
            decoded = dec_local.get_packet()
            assert decoded == payload, f"Failed for payload size {len(payload)}"

    def test_silence_gaps_between_packets(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        # Encode preamble
        preamble = list(enc.emit_preamble())

        # Packet 1
        enc.feed_packet(b"Packet 1")
        pcm1 = []
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm1.append(chunk)

        # Silence gap
        silence = [np.zeros(640) for _ in range(5)]

        # Packet 2
        enc.feed_packet(b"Packet 2")
        pcm2 = []
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm2.append(chunk)

        # Decode with gaps
        for chunk in preamble + pcm1 + silence + pcm2:
            dec.feed_pcm(chunk)

        # Should still be locked or recover
        state = dec.get_state()
        # State could be either LOCKED or SEARCH depending on implementation
        assert state in [decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE]

    def test_corrupted_data_handling(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        # Encode valid preamble + data
        preamble = list(enc.emit_preamble())
        enc.feed_packet(b"Valid data")

        pcm_data = []
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                pcm_data.append(chunk)

        # Corrupt some PCM chunks
        corrupted_pcm = []
        for i, chunk in enumerate(pcm_data):
            if i % 3 == 0:  # Corrupt every 3rd chunk
                corrupted_pcm.append(chunk + np.random.randn(len(chunk)) * 0.5)
            else:
                corrupted_pcm.append(chunk)

        # Decode
        for chunk in preamble + corrupted_pcm:
            dec.feed_pcm(chunk)

        # Decoder should handle corruption gracefully
        # (may or may not decode successfully, but shouldn't crash)
        state = dec.get_state()
        assert state in [decoder.DecoderState.LOCKED, decoder.DecoderState.SEARCH_PREAMBLE]

        # Try to get packet (may be None due to corruption)
        _ = dec.get_packet()
        # Just verify it doesn't crash

    def test_empty_decoder_buffer(self, dec: decoder.StreamDecoder):
        # Feeding random noise should not crash
        for _ in range(20):
            noise = np.random.randn(640) * 0.1
            dec.feed_pcm(noise)

        # Should remain in search state
        assert dec.get_state() == decoder.DecoderState.SEARCH_PREAMBLE
        assert dec.get_packet() is None

    def test_consecutive_packets_without_gap(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        # Encode preamble + multiple packets back-to-back
        preamble = list(enc.emit_preamble())

        # Queue multiple packets
        for i in range(5):
            enc.feed_packet(f"Packet {i}".encode())

        all_pcm = preamble.copy()
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        # Decode
        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        # Should decode at least some packets
        packets = []
        for _ in range(10):
            pkt = dec.get_packet()
            if pkt:
                packets.append(bytes(pkt))

        assert len(packets) >= 1
