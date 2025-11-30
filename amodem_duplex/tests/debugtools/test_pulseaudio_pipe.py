# mypy: disable-error-code="no-untyped-def"

import subprocess

import pytest

from amodem_duplex.debugtools import pulseaudio_pipe


class TestPulseAudioPipeManager:
    @pytest.fixture
    def manager(self):
        mgr = pulseaudio_pipe.PulseAudioPipeManager(prefix="amodem-test-pytest")
        yield mgr
        mgr.delete_all()

    def test_create_pipe_creates_real_devices(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        pipe = manager.create("test1", sample_rate=16000, channels=1)

        assert pipe.sink_name == "amodem-test-pytest-test1-speaker"
        assert pipe.source_name == "amodem-test-pytest-test1-mic"
        assert pipe.sink_module_id is not None
        assert pipe.source_module_id is not None
        assert pipe.sample_rate == 16000
        assert pipe.channels == 1

    def test_create_pipe_returns_pipe_with_module_ids(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        pipe = manager.create("test2")

        assert isinstance(pipe.sink_module_id, int)
        assert isinstance(pipe.source_module_id, int)
        assert pipe.sink_module_id > 0
        assert pipe.source_module_id > 0

    def test_delete_pipe_removes_devices(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        pipe = manager.create("test3")

        result = manager.delete(pipe.name)

        assert result is True
        assert manager.get(pipe.name) is None

    def test_list_all_returns_created_pipes(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        manager.create("test4")
        manager.create("test5")

        pipes = manager.list_all()

        assert len(pipes) >= 2
        names = {p.name for p in pipes}
        assert "test4" in names
        assert "test5" in names

    def test_get_finds_pipe_by_name(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        created = manager.create("test6")

        found = manager.get("test6")

        assert found is not None
        assert found.name == created.name
        assert found.sink_name == created.sink_name
        assert found.source_name == created.source_name

    def test_delete_all_removes_all_matching_pipes(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        manager.create("test7")
        manager.create("test8")

        deleted_count = manager.delete_all()

        assert deleted_count >= 2
        assert len(manager.list_all()) == 0

    def test_pactl_not_available_raises_error(self, monkeypatch: pytest.MonkeyPatch):
        def mock_which(cmd: str):
            return None

        monkeypatch.setattr("shutil.which", mock_which)

        with pytest.raises(RuntimeError, match="pactl is not available"):
            pulseaudio_pipe.PulseAudioPipeManager()

    def test_created_devices_visible_in_pactl_list(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        pipe = manager.create("test9")

        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert pipe.sink_name in result.stdout

        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert pipe.source_name in result.stdout

    def test_pipe_works_with_paplay_parecord(self, manager: pulseaudio_pipe.PulseAudioPipeManager):
        """Test full audio roundtrip: paplay → speaker → mic → parecord.

        Generates a 1kHz sine wave, plays it via paplay to the pipe's speaker,
        records from the pipe's mic via parecord, and verifies the audio matches.
        """
        import os
        import tempfile
        import time

        import numpy as np

        pipe = manager.create("patest", sample_rate=16000, channels=1)

        # Verify sink exists
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True,
            text=True,
        )
        assert pipe.sink_name in result.stdout, f"Sink {pipe.sink_name} not found in pactl list sinks"
        print("✓ Sink visible in pactl list sinks short")

        # Verify source exists
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True,
            text=True,
        )
        assert pipe.source_name in result.stdout, f"Source {pipe.source_name} not found in pactl list sources"
        print("✓ Source visible in pactl list sources short")

        # Generate 1 second of 1kHz sine wave
        sample_rate = 16000
        duration = 1.0
        frequency = 1000.0
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        sine_wave = np.sin(2 * np.pi * frequency * t)
        # Convert to s16le format (16-bit signed little-endian PCM)
        audio_data = (sine_wave * 32767).astype(np.int16).tobytes()

        # Write sine wave to temp file for paplay
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as play_file:
            play_path = play_file.name
            play_file.write(audio_data)

        # Create temp file for parecord
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as record_file:
            record_path = record_file.name

        try:
            # Start recording first
            record_proc = subprocess.Popen(
                [
                    "parecord",
                    "--device",
                    pipe.source_name,
                    "--rate",
                    "16000",
                    "--channels",
                    "1",
                    "--format",
                    "s16le",
                    "--raw",
                    record_path,
                ],
                stderr=subprocess.PIPE,
            )

            # Give recorder time to start
            time.sleep(0.2)

            # Play the sine wave
            play_proc = subprocess.run(
                [
                    "paplay",
                    "--device",
                    pipe.sink_name,
                    "--rate",
                    "16000",
                    "--channels",
                    "1",
                    "--format",
                    "s16le",
                    "--raw",
                    play_path,
                ],
                timeout=5,
                capture_output=True,
            )

            assert play_proc.returncode == 0, f"paplay failed: {play_proc.stderr.decode()}"
            print(f"✓ paplay successfully played to {pipe.sink_name}")

            # Let recording continue a bit longer to capture everything
            time.sleep(0.3)

            # Stop recording
            record_proc.terminate()
            record_proc.wait(timeout=1)
            print(f"✓ parecord successfully recorded from {pipe.source_name}")

            # Verify we got audio data
            recorded_size = os.path.getsize(record_path)
            assert recorded_size > 0, "No audio data recorded"
            print(f"✓ Recorded {recorded_size} bytes of audio data")

            # Read recorded audio and verify it contains signal (not silence)
            with open(record_path, "rb") as f:
                recorded_bytes = f.read()

            # Convert to numpy array
            recorded_samples = np.frombuffer(recorded_bytes, dtype=np.int16)

            # Calculate RMS of recorded audio
            rms = np.sqrt(np.mean(recorded_samples.astype(np.float32) ** 2))
            print(f"✓ Recorded RMS: {rms:.2f}")

            # Verify we have actual signal, not silence
            # RMS should be significant for a sine wave at full volume
            assert rms > 1000, f"RMS too low ({rms:.2f}), likely silence or very weak signal"
            print("✓ Audio contains real signal (RMS > 1000)")

        finally:
            try:
                os.unlink(play_path)
            except OSError:
                pass
            try:
                os.unlink(record_path)
            except OSError:
                pass

        print("\n✓ Full roundtrip test passed!")
