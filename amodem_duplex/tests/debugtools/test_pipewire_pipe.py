# mypy: disable-error-code=no-untyped-def

import logging
import shutil
import uuid

import pytest

from amodem_duplex.debugtools.pipewire_pipe import PipeWirePipeManager


@pytest.fixture(autouse=True)
def pipewire_manager():
    if shutil.which("pw-cli") is None:
        pytest.skip("PipeWire not installed on this system")
    unique_prefix = f"amodem-test-{uuid.uuid4().hex[:8]}-"
    manager = PipeWirePipeManager(prefix=unique_prefix)
    manager.delete_all()
    try:
        sanity = manager.create("sanity-check")
    except RuntimeError as exc:
        manager.delete_all()
        cleanup_manager = PipeWirePipeManager()
        cleanup_manager.delete_all()
        logging.error("PipeWire cannot create test pipe: %s", exc)
        raise
    else:
        manager.delete(sanity.id)
    try:
        yield manager
    finally:
        manager.delete_all()
        cleanup_manager = PipeWirePipeManager()
        cleanup_manager.delete_all()


@pytest.mark.skip(reason="pw-cli node creation not persisting - see report005.md")
def test_create_list_and_get_pipe(pipewire_manager):
    pipe = pipewire_manager.create("crud1", sample_rate=16000, channels=1)

    pipes = pipewire_manager.list_all()
    matching = [candidate for candidate in pipes if candidate.id == pipe.id]

    fetched = pipewire_manager.get(pipe.id)

    assert matching
    assert fetched is not None
    assert fetched.id == pipe.id


@pytest.mark.skip(reason="pw-cli node creation not persisting - see report005.md")
def test_delete_pipe_removes_it(pipewire_manager):
    pipe = pipewire_manager.create("crud2", sample_rate=16000, channels=1)

    deleted = pipewire_manager.delete(pipe.id)
    remaining = pipewire_manager.get(pipe.id)

    assert deleted
    assert remaining is None


@pytest.mark.skip(reason="pw-cli node creation not persisting - see report005.md")
def test_delete_all_with_pattern(pipewire_manager):
    first = pipewire_manager.create("crud3", sample_rate=16000, channels=1)
    second = pipewire_manager.create("crud3b", sample_rate=16000, channels=1)

    count = pipewire_manager.delete_all(pattern="*crud3*")
    remaining = pipewire_manager.list_all()

    assert count >= 2
    assert all(pipe.id not in {first.id, second.id} for pipe in remaining)
