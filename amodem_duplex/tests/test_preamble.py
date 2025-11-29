# mypy: disable-error-code="no-untyped-def"

"""Tests for preamble generation helper."""

import io

import numpy as np
import pytest

import amodem.config
import amodem.equalizer
import amodem.send
from amodem_duplex import preamble


class TestPreambleGeneration:
    @pytest.fixture
    def config(self):
        return amodem.config.slowest()

    def test_generate_preamble_returns_numpy_array(self, config: amodem.config.Configuration):
        result = preamble.generate_preamble_pcm(config)

        assert isinstance(result, np.ndarray)
        assert result.dtype in (np.float64, np.float32, np.float_)

    def test_preamble_length_matches_expected(self, config: amodem.config.Configuration):
        result = preamble.generate_preamble_pcm(config)

        # Expected components (NOT including silence_start):
        # 1. Prefix: len(equalizer.prefix) * config.Nsym
        # 2. Training with silence: equalizer.equalizer_length * config.Nsym + 2 * equalizer.silence_length * config.Nsym

        prefix_samples = len(amodem.equalizer.prefix) * config.Nsym
        training_samples = amodem.equalizer.equalizer_length * config.Nsym
        silence_around_training = 2 * amodem.equalizer.silence_length * config.Nsym

        expected_length = prefix_samples + training_samples + silence_around_training

        assert len(result) == expected_length

    def test_preamble_contains_carrier_prefix(self, config: amodem.config.Configuration):
        result = preamble.generate_preamble_pcm(config)

        # The prefix section should be at the beginning (no silence_start)
        prefix_samples = len(amodem.equalizer.prefix) * config.Nsym
        prefix_section = result[:prefix_samples]

        # Check that it's not silence
        assert np.abs(prefix_section).max() > 0.1

    def test_preamble_matches_sender_output(self, config: amodem.config.Configuration):
        # Generate preamble using our function
        our_preamble = preamble.generate_preamble_pcm(config)

        # Generate preamble using amodem.send.Sender (without silence_start)
        buffer = io.BytesIO()
        sender = amodem.send.Sender(buffer, config=config, gain=1.0)

        # Capture what Sender.start() writes (does NOT include silence_start)
        sender.start()

        # Read the captured PCM data
        # Note: Sender uses common.dumps which converts to int16 and scales by 32000
        # We need to convert back: int16 -> float64 / 32000
        buffer.seek(0)
        sender_data = buffer.read()
        sender_pcm_int16 = np.frombuffer(sender_data, dtype=np.int16)
        sender_pcm = sender_pcm_int16.astype(np.float64) / 32000.0

        # They should be identical
        assert len(our_preamble) == len(sender_pcm)
        np.testing.assert_allclose(our_preamble, sender_pcm, rtol=1e-4, atol=1e-4)

    def test_get_preamble_duration(self, config: amodem.config.Configuration):
        result = preamble.get_preamble_duration(config)

        assert isinstance(result, float)
        assert result > 0

        # Duration should match: PCM length / sample rate
        pcm = preamble.generate_preamble_pcm(config)
        expected_duration = len(pcm) / config.Fs

        assert abs(result - expected_duration) < 1e-6

    def test_preamble_different_configs(self):
        # Test with a couple different configs to ensure generality
        for bitrate in [1, 8, 32]:
            cfg = amodem.config.bitrates[bitrate]
            pcm = preamble.generate_preamble_pcm(cfg)
            duration = preamble.get_preamble_duration(cfg)

            assert len(pcm) > 0
            assert duration > 0
            assert abs(duration - len(pcm) / cfg.Fs) < 1e-6
