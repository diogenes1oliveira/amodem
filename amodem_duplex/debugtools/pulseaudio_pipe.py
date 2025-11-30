"""PulseAudio debugging utilities."""

import dataclasses
import fnmatch
import shutil
import subprocess

import loguru

LOGGER = loguru.logger


@dataclasses.dataclass
class PulseAudioPipe:
    """Represents a virtual PulseAudio pipe (null sink + remap source)."""

    id: str
    name: str
    sink_name: str
    source_name: str
    sink_module_id: int | None
    source_module_id: int | None
    sample_rate: int
    channels: int


class PulseAudioPipeManager:
    """Creates, lists, and deletes PulseAudio pipes via `pactl`."""

    def __init__(
        self,
        prefix: str = "amodem-test",
        suffix_input: str = "mic",
        suffix_output: str = "speaker",
    ) -> None:
        """Initialize PulseAudio pipe manager.

        Args:
            prefix: Prefix for pipe names (use underscores/dashes, no normalization)
            suffix_input: Suffix for input/source devices
            suffix_output: Suffix for output/sink devices

        Raises:
            RuntimeError: If pactl is not available in PATH
        """
        self.prefix = prefix
        self.suffix_input = suffix_input
        self.suffix_output = suffix_output

        self._pactl_path = shutil.which("pactl")
        if not self._pactl_path:
            raise RuntimeError("pactl is not available in PATH")

    def create(self, name: str, sample_rate: int = 16000, channels: int = 1) -> PulseAudioPipe:
        """Create a new PulseAudio pipe (null sink + remap source).

        Args:
            name: Name for the pipe
            sample_rate: Sample rate in Hz
            channels: Number of audio channels

        Returns:
            PulseAudioPipe with module IDs

        Raises:
            ValueError: If name is empty
            RuntimeError: If pactl command fails
        """
        if not name:
            raise ValueError("name cannot be empty")

        sink_name = self._build_entity_name(name, "output")
        source_name = self._build_entity_name(name, "input")

        sink_module_id = self._create_null_sink(sink_name, sample_rate, channels)
        source_module_id = self._create_remap_source(source_name, f"{sink_name}.monitor")

        LOGGER.info(
            f"Created pipe '{name}' (sink={sink_name}, source={source_name}, "
            f"rate={sample_rate}Hz, channels={channels}, sink_module={sink_module_id}, source_module={source_module_id})"
        )

        return PulseAudioPipe(
            id=self._build_pipe_id(name),
            name=name,
            sink_name=sink_name,
            source_name=source_name,
            sink_module_id=sink_module_id,
            source_module_id=source_module_id,
            sample_rate=sample_rate,
            channels=channels,
        )

    def list_all(self, pattern: str | None = None) -> list[PulseAudioPipe]:
        """List all PulseAudio pipes.

        Args:
            pattern: Optional glob pattern to filter pipes

        Returns:
            List of matching pipes (including orphaned sinks without sources)
        """
        nodes = self._list_nodes()
        sinks: dict[str, int] = {}
        sources: dict[str, int] = {}

        for node_id, node_info in nodes.items():
            node_name = node_info.get("node.name")
            if not node_name:
                continue
            media_class = node_info.get("media.class", "")
            if "Audio/Sink" in media_class:
                sinks[node_name] = node_id
            elif "Audio/Source" in media_class:
                sources[node_name] = node_id

        pipes: list[PulseAudioPipe] = []
        for sink_name, _sink_index in sinks.items():
            if not sink_name.startswith(self.prefix):
                continue

            name_part = sink_name[len(self.prefix) + 1 :]
            if name_part.endswith(f"-{self.suffix_output}"):
                pipe_name = name_part[: -len(f"-{self.suffix_output}")]
            else:
                continue

            source_name = self._build_entity_name(pipe_name, "input")
            # Include pipes even if source is missing (orphaned sink)
            pipe = PulseAudioPipe(
                id=self._build_pipe_id(pipe_name),
                name=pipe_name,
                sink_name=sink_name,
                source_name=source_name,
                sink_module_id=None,
                source_module_id=None,
                sample_rate=16000,
                channels=1,
            )
            pipes.append(pipe)

        if pattern:
            pipes = [
                pipe for pipe in pipes if any(fnmatch.fnmatchcase(value, pattern) for value in (pipe.id, pipe.name))
            ]
        return pipes

    def get(self, identifier: str) -> PulseAudioPipe | None:
        """Get a single pipe by name or ID.

        Args:
            identifier: Pipe name or ID

        Returns:
            Pipe if found, None otherwise
        """
        for pipe in self.list_all():
            if identifier in {pipe.id, pipe.name, pipe.sink_name, pipe.source_name}:
                return pipe
        return None

    def delete(self, identifier: str) -> bool:
        """Delete a pipe by name or ID.

        Args:
            identifier: Pipe name or ID

        Returns:
            True if pipe was deleted, False otherwise
        """
        pipe = self.get(identifier)
        if pipe is None:
            return False

        # Find module IDs from pactl list modules
        sink_module_id = self._find_module_id_for_sink(pipe.sink_name)
        source_module_id = self._find_module_id_for_source(pipe.source_name)

        sink_ok = self._unload_module(sink_module_id)
        source_ok = self._unload_module(source_module_id)

        if sink_ok or source_ok:
            LOGGER.info(f"Deleted pipe '{identifier}' (sink_module={sink_module_id}, source_module={source_module_id})")
        else:
            LOGGER.warning(f"Failed to delete pipe '{identifier}'")

        return sink_ok or source_ok

    def _find_module_id_for_sink(self, sink_name: str) -> int | None:
        """Find module ID for a sink by name."""
        result = subprocess.run(
            ["pactl", "list", "modules", "short"],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.strip().split("\n"):
            if f"sink_name={sink_name}" in line:
                parts = line.split()
                if parts:
                    return int(parts[0])
        return None

    def _find_module_id_for_source(self, source_name: str) -> int | None:
        """Find module ID for a source by name."""
        result = subprocess.run(
            ["pactl", "list", "modules", "short"],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.strip().split("\n"):
            if f"source_name={source_name}" in line:
                parts = line.split()
                if parts:
                    return int(parts[0])
        return None

    def delete_all(self, pattern: str | None = None) -> int:
        """Delete all pipes matching optional pattern.

        Args:
            pattern: Optional glob pattern to filter pipes

        Returns:
            Number of pipes deleted
        """
        deleted = 0
        for pipe in self.list_all(pattern):
            if self.delete(pipe.id):
                deleted += 1

        LOGGER.info(f"Deleted {deleted} pipe(s) matching pattern '{pattern}'")
        return deleted

    def _create_null_sink(self, sink_name: str, sample_rate: int, channels: int) -> int:
        """Create null sink using pactl load-module.

        Args:
            sink_name: Name for the sink
            sample_rate: Sample rate in Hz
            channels: Number of channels

        Returns:
            Module ID

        Raises:
            RuntimeError: If pactl command fails
        """
        args = [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={sink_name}",
            f"sink_properties=device.description={sink_name}",
            f"rate={sample_rate}",
            f"channels={channels}",
        ]

        result = subprocess.run(args, check=True, capture_output=True, text=True)
        return int(result.stdout.strip())

    def _create_remap_source(self, source_name: str, master: str) -> int:
        """Create remap source using pactl load-module.

        Args:
            source_name: Name for the source
            master: Master sink to monitor

        Returns:
            Module ID

        Raises:
            RuntimeError: If pactl command fails
        """
        args = [
            "pactl",
            "load-module",
            "module-remap-source",
            f"source_name={source_name}",
            f"master={master}",
            f"source_properties=device.description={source_name}",
        ]

        result = subprocess.run(args, check=True, capture_output=True, text=True)
        return int(result.stdout.strip())

    def _unload_module(self, module_id: int | None) -> bool:
        """Unload module using pactl.

        Args:
            module_id: Module ID to unload

        Returns:
            True if successful, False otherwise
        """
        if module_id is None:
            return False
        try:
            subprocess.run(
                ["pactl", "unload-module", str(module_id)],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def _list_nodes(self) -> dict[int, dict[str, str]]:
        """List all sinks and sources using pactl.

        Returns:
            Dictionary mapping node IDs to their properties
        """
        nodes = {}

        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                sink_id = int(parts[0])
                sink_name = parts[1]
                nodes[sink_id] = {
                    "node.name": sink_name,
                    "media.class": "Audio/Sink",
                }

        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                source_id = int(parts[0])
                source_name = parts[1]
                nodes[source_id] = {
                    "node.name": source_name,
                    "media.class": "Audio/Source",
                }

        return nodes

    def _build_pipe_id(self, name: str) -> str:
        """Build pipe ID from name.

        Args:
            name: Pipe name

        Returns:
            Full pipe ID
        """
        return f"{self.prefix}-{name}"

    def _build_entity_name(self, name: str, suffix_type: str) -> str:
        """Build entity name (sink or source) from name and type.

        Args:
            name: Pipe name
            suffix_type: Either "input" or "output"

        Returns:
            Full entity name
        """
        suffix = self.suffix_output if suffix_type == "output" else self.suffix_input
        pipe_id = self._build_pipe_id(name)
        return f"{pipe_id}-{suffix}"
