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
