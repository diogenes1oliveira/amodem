# mypy: disable-error-code="no-untyped-def,assignment,arg-type"

"""Realistic usage scenario tests for amodem_duplex.

These tests demonstrate how amodem_duplex would be used in real applications:
- Chat/messaging with small frequent packets
- File transfer with chunked data
- Request-response patterns like APIs
- Continuous streaming with heartbeats
- Mixed workloads combining multiple patterns
"""


import pytest

import amodem.config
from amodem_duplex import decoder, encoder


class TestRealisticScenarios:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    @pytest.fixture
    def enc(self, config):
        return encoder.StreamEncoder(config, chunk_samples=640)

    @pytest.fixture
    def dec(self, config):
        return decoder.StreamDecoder(config, crc_error_threshold=3)

    def _encode_and_decode(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder, packets: list):
        """Helper to encode multiple packets and decode them all."""
        all_pcm = list(enc.emit_preamble())

        for pkt in packets:
            enc.feed_packet(pkt)

        # Encoder now auto-flushes partial chunks when no more data is coming
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        decoded = []
        for _ in range(len(packets) + 5):
            pkt = dec.get_packet()
            if pkt is not None:
                decoded.append(bytes(pkt))

        return decoded

    # ===== Chat/Messaging Scenarios (5 tests) =====

    def test_chat_conversation_short_messages(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        messages = [
            b"Hi there!",
            b"How are you?",
            b"I'm good thanks",
            b"What's up?",
            b"Not much",
            b"Cool",
            b"Talk later?",
            b"Sure!",
            b"Bye",
            b"Bye!",
        ]

        decoded = self._encode_and_decode(enc, dec, messages)

        assert len(decoded) == len(messages)
        assert decoded == messages

    def test_chat_with_emoji_unicode(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        messages = [
            "Hello 👋".encode(),
            "How are you? 😊".encode(),
            "Great! 🎉".encode(),
            "Coffee? ☕".encode(),
            "Sure! 👍".encode(),
        ]

        decoded = self._encode_and_decode(enc, dec, messages)

        assert len(decoded) == len(messages)
        assert decoded == messages

    def test_chat_burst_then_idle(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        burst1 = [b"msg1", b"msg2", b"msg3", b"msg4", b"msg5"]
        burst2 = [b"msg6", b"msg7", b"msg8"]

        decoded1 = self._encode_and_decode(enc, dec, burst1)

        assert len(decoded1) == len(burst1)
        assert decoded1 == burst1

        enc2 = encoder.StreamEncoder(enc.config, chunk_samples=640)
        dec2 = decoder.StreamDecoder(dec.config, crc_error_threshold=3)
        decoded2 = self._encode_and_decode(enc2, dec2, burst2)

        assert len(decoded2) == len(burst2)
        assert decoded2 == burst2

    def test_chat_typing_indicators(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        indicators = [b".", b"..", b"...", b"....", b"....."]

        decoded = self._encode_and_decode(enc, dec, indicators)

        assert len(decoded) == len(indicators)
        assert decoded == indicators

    def test_chat_mixed_message_sizes(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        messages = [
            b"Hi",
            b"This is a medium length message with more content",
            b"K",
            b"Here's another longer message that contains quite a bit more information than the previous short ones and should test the decoder's ability to handle varying packet sizes",
            b"Ok",
        ]

        decoded = self._encode_and_decode(enc, dec, messages)

        assert len(decoded) == len(messages)
        assert decoded == messages

    # ===== File Transfer Scenarios (4 tests) =====

    def test_file_transfer_1kb_in_chunks(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        data = b"X" * 1024
        chunk_size = 50
        chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

        decoded = self._encode_and_decode(enc, dec, chunks)

        assert len(decoded) == len(chunks)
        reconstructed = b"".join(decoded)
        assert reconstructed == data

    def test_file_transfer_with_ack_pattern(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [
            b"DATA:chunk1",
            b"ACK:1",
            b"DATA:chunk2",
            b"ACK:2",
            b"DATA:chunk3",
            b"ACK:3",
        ]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    def test_file_transfer_sequential_chunks(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        chunks = [f"CHUNK{i:03d}:".encode() + b"X" * 50 for i in range(20)]

        decoded = self._encode_and_decode(enc, dec, chunks)

        assert len(decoded) == len(chunks)
        assert decoded == chunks

    def test_file_transfer_with_metadata(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [b"HEADER:file.txt:1024"]
        packets.extend([b"DATA:" + b"X" * 50 for _ in range(10)])
        packets.append(b"FOOTER:CRC:12345")

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    # ===== Request-Response Patterns (4 tests) =====

    def test_request_response_simple(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [
            b"REQUEST:get_user:123",
            b"RESPONSE:user:john",
        ]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    def test_request_response_rapid_fire(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [
            b"REQ:1",
            b"REQ:2",
            b"REQ:3",
            b"REQ:4",
            b"RESP:1:OK",
            b"RESP:2:OK",
            b"RESP:3:OK",
            b"RESP:4:OK",
        ]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    def test_request_response_with_errors(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [
            b"REQUEST:get_user:123",
            b"RESPONSE:OK:user_data",
            b"REQUEST:get_user:999",
            b"RESPONSE:ERROR:not_found",
            b"REQUEST:get_user:456",
            b"RESPONSE:OK:user_data_2",
        ]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    def test_request_response_json_like(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [
            b'{"type":"request","id":1,"method":"get"}',
            b'{"type":"response","id":1,"status":"ok","data":"value"}',
            b'{"type":"request","id":2,"method":"post"}',
            b'{"type":"response","id":2,"status":"ok"}',
        ]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    # ===== Continuous Streaming (5 tests) =====

    def test_streaming_with_periodic_preambles(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets1 = [b"data1", b"data2", b"data3"]

        all_pcm = list(enc.emit_preamble())
        for pkt in packets1:
            enc.feed_packet(pkt)
        while enc.has_data():
            chunk = enc.get_pcm_chunk()
            if chunk is not None:
                all_pcm.append(chunk)

        enc2 = encoder.StreamEncoder(enc.config, chunk_samples=640)
        preamble2 = list(enc2.emit_preamble())
        packets2 = [b"data4", b"data5", b"data6"]
        for pkt in packets2:
            enc2.feed_packet(pkt)
        while enc2.has_data():
            chunk = enc2.get_pcm_chunk()
            if chunk is not None:
                preamble2.append(chunk)

        for chunk in all_pcm:
            dec.feed_pcm(chunk)

        decoded1 = []
        for _ in range(len(packets1) + 2):
            pkt = dec.get_packet()
            if pkt is not None:
                decoded1.append(bytes(pkt))

        assert len(decoded1) == len(packets1)
        assert decoded1 == packets1

        for chunk in preamble2:
            dec.feed_pcm(chunk)

        decoded2 = []
        for _ in range(len(packets2) + 2):
            pkt = dec.get_packet()
            if pkt is not None:
                decoded2.append(bytes(pkt))

        assert len(decoded2) == len(packets2)
        assert decoded2 == packets2

    def test_streaming_with_heartbeats(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [
            b"data1",
            encoder.HEARTBEAT_MARKER,
            b"data2",
            encoder.HEARTBEAT_MARKER,
            b"data3",
        ]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        data_packets = [p for p in decoded if p != encoder.HEARTBEAT_MARKER]
        assert data_packets == [b"data1", b"data2", b"data3"]

    def test_streaming_idle_periods_with_heartbeat(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        phase1 = [b"data1", b"data2"]
        phase2 = [encoder.HEARTBEAT_MARKER]
        phase3 = [b"data3", b"data4"]

        all_packets = phase1 + phase2 + phase3
        decoded = self._encode_and_decode(enc, dec, all_packets)

        assert len(decoded) == len(all_packets)
        data_only = [p for p in decoded if p != encoder.HEARTBEAT_MARKER]
        assert data_only == [b"data1", b"data2", b"data3", b"data4"]

    def test_streaming_session_restart(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        session1_packets = [b"session1_data1", b"session1_data2"]
        decoded1 = self._encode_and_decode(enc, dec, session1_packets)

        assert len(decoded1) == len(session1_packets)
        assert decoded1 == session1_packets

        enc2 = encoder.StreamEncoder(enc.config, chunk_samples=640)
        dec2 = decoder.StreamDecoder(dec.config, crc_error_threshold=3)
        session2_packets = [b"session2_data1", b"session2_data2"]
        decoded2 = self._encode_and_decode(enc2, dec2, session2_packets)

        assert len(decoded2) == len(session2_packets)
        assert decoded2 == session2_packets

    def test_streaming_many_packets_continuous(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = [f"packet_{i:03d}".encode() for i in range(50)]

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    # ===== Mixed Realistic Workloads (3 tests) =====

    def test_mixed_workload_all_patterns(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = []

        packets.extend([b"chat:hello", b"chat:hi"])

        packets.extend([b"file:chunk1", b"file:chunk2", b"file:chunk3"])

        packets.extend([b"req:get_status", b"resp:status_ok"])

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    def test_mixed_packet_sizes_realistic(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = []

        packets.extend([b"S" * 10 for _ in range(7)])

        packets.extend([b"M" * 100 for _ in range(2)])

        packets.append(b"L" * 200)

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets

    def test_mixed_timing_patterns(self, enc: encoder.StreamEncoder, dec: decoder.StreamDecoder):
        packets = []

        packets.extend([b"burst1", b"burst2", b"burst3"])

        packets.extend([b"steady1", b"steady2"])

        packets.extend([b"final1", b"final2", b"final3", b"final4"])

        decoded = self._encode_and_decode(enc, dec, packets)

        assert len(decoded) == len(packets)
        assert decoded == packets
