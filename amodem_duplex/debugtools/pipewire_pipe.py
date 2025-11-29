"""PipeWire debugging utilities."""

import dataclasses
import fnmatch
import json
import re
import shlex
import shutil
import subprocess
import time

import loguru

LOGGER = loguru.logger


@dataclasses.dataclass
class PipeWirePipe:
    """Represents a virtual PipeWire pipe (null sink + remap source)."""

    id: str
    name: str
    sink_name: str
    source_name: str
    sink_node_id: int | None
    source_node_id: int | None
    sample_rate: int
    channels: int


class PipeWirePipeManager:
    """Creates, lists, and deletes PipeWire pipes via `pw-cli`."""

    def __init__(
        self,
        prefix: str = "amodem-test-",
        suffix_input: str = " Mic",
        suffix_output: str = " Speaker",
    ) -> None:
        self.prefix = prefix
        self.suffix_input = suffix_input
        self.suffix_output = suffix_output
        self.prefix_id = self._normalize_name(prefix)
        self.suffix_input_id = self._normalize_name(suffix_input)
        self.suffix_output_id = self._normalize_name(suffix_output)
        self._pw_cli_path = shutil.which("pw-cli")
        self._pw_dump_path = shutil.which("pw-dump")
        if not self._pw_cli_path:
            raise RuntimeError("pw-cli is not available in PATH")
        if not self._pw_dump_path:
            raise RuntimeError("pw-dump is not available in PATH")

    def create(self, name: str, sample_rate: int = 16000, channels: int = 1) -> PipeWirePipe:
        normalized_name = self._normalize_name(name)
        if not normalized_name:
            raise ValueError("name must contain at least one valid character")
        sink_name = self._build_entity_name(normalized_name, "output")
        source_name = self._build_entity_name(normalized_name, "input")
        sink_description = self._build_description(name, "output")
        source_description = self._build_description(name, "input")
        sink_node_id = self._create_null_sink(sink_name, sink_description, sample_rate, channels)
        source_node_id = self._create_virtual_source(source_name, sink_name, source_description)
        return PipeWirePipe(
            id=self._build_pipe_id(normalized_name),
            name=normalized_name,
            sink_name=sink_name,
            source_name=source_name,
            sink_node_id=sink_node_id,
            source_node_id=source_node_id,
            sample_rate=sample_rate,
            channels=channels,
        )

    def list_all(self, pattern: str | None = None) -> list[PipeWirePipe]:
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

        pipes: list[PipeWirePipe] = []
        for sink_name, sink_node_id in sinks.items():
            normalized = self._extract_normalized_name(sink_name)
            if normalized is None:
                continue
            source_name = self._build_entity_name(normalized, "input")
            if source_name not in sources:
                continue
            pipe = PipeWirePipe(
                id=self._build_pipe_id(normalized),
                name=normalized,
                sink_name=sink_name,
                source_name=source_name,
                sink_node_id=sink_node_id,
                source_node_id=sources[source_name],
                sample_rate=16000,
                channels=1,
            )
            pipes.append(pipe)

        if pattern:
            pipes = [
                pipe for pipe in pipes if any(fnmatch.fnmatchcase(value, pattern) for value in (pipe.id, pipe.name))
            ]
        return pipes

    def get(self, identifier: str) -> PipeWirePipe | None:
        for pipe in self.list_all():
            if identifier in {pipe.id, pipe.name, pipe.sink_name, pipe.source_name}:
                return pipe
        return None

    def delete(self, identifier: str) -> bool:
        pipe = self.get(identifier)
        if pipe is None:
            return False
        sink_destroyed = self._destroy_node(pipe.sink_node_id)
        source_destroyed = self._destroy_node(pipe.source_node_id)
        return sink_destroyed or source_destroyed

    def delete_all(self, pattern: str | None = None) -> int:
        deleted = 0
        for pipe in self.list_all(pattern):
            if self.delete(pipe.id):
                deleted += 1
        return deleted

    @staticmethod
    def _normalize_name(name: str) -> str:
        sanitized = name.lower()
        sanitized = re.sub(r"[^a-z0-9.-]+", "-", sanitized)
        sanitized = re.sub(r"-{2,}", "-", sanitized)
        return sanitized.strip("-")

    def _build_pipe_id(self, normalized_name: str) -> str:
        return f"{self.prefix_id}-{normalized_name}"

    def _build_entity_name(self, normalized_name: str, suffix_type: str) -> str:
        suffix_id = self.suffix_output_id if suffix_type == "output" else self.suffix_input_id
        base = self._build_pipe_id(normalized_name)
        return f"{base}-{suffix_id}" if suffix_id else base

    def _build_description(self, name: str, suffix_type: str) -> str:
        suffix = self.suffix_output if suffix_type == "output" else self.suffix_input
        return f"{self.prefix} {name}{suffix} {'Output' if suffix_type == 'output' else 'Input'}"

    def _extract_normalized_name(self, sink_name: str) -> str | None:
        prefix_segment = f"{self.prefix_id}-"
        if not sink_name.startswith(prefix_segment):
            return None
        normalized = sink_name[len(prefix_segment) :]
        suffix_segment = f"-{self.suffix_output_id}" if self.suffix_output_id else ""
        if suffix_segment:
            if not normalized.endswith(self.suffix_output_id):
                return None
            normalized = normalized[: -len(suffix_segment)]
        return normalized.strip("-")

    def _list_nodes(self) -> dict[int, dict[str, str]]:
        output = self._run_pw_dump()
        nodes: dict[int, dict[str, str]] = {}

        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse pw-dump output: {exc}") from exc

        for obj in data:
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            node_id = obj.get("id")
            if node_id is None:
                continue
            props = obj.get("info", {}).get("props", {})
            nodes[node_id] = {
                "node.name": props.get("node.name", ""),
                "media.class": props.get("media.class", ""),
                "node.description": props.get("node.description", ""),
            }

        return nodes

    def _create_null_sink(self, sink_name: str, description: str, sample_rate: int, channels: int) -> int:
        args = [
            "create-node",
            "adapter",
            "factory.name=support.null-audio-sink",
            f"node.name={sink_name}",
            f"node.description={description}",
            f"audio.rate={sample_rate}",
            f"audio.channels={channels}",
            "media.class=Audio/Sink",
            "object.linger=1",
        ]
        self._run_pw_cli(args)
        # pw-cli create-node returns a proxy reference, not the actual ID
        # We need to query pw-dump to find the node by name
        return self._find_node_id_by_name(sink_name)

    def _create_virtual_source(self, source_name: str, master: str, description: str) -> int:
        args = [
            "create-node",
            "adapter",
            "factory.name=support.null-audio-sink",
            f"node.name={source_name}",
            f"node.description={description}",
            "audio.rate=16000",
            "audio.channels=1",
            "media.class=Audio/Source/Virtual",
            "audio.position=MONO",
            f"target.object={master}",
            "object.linger=1",
        ]
        self._run_pw_cli(args)
        # pw-cli create-node returns a proxy reference, not the actual ID
        # We need to query pw-dump to find the node by name
        return self._find_node_id_by_name(source_name)

    def _find_node_id_by_name(self, node_name: str) -> int:
        # Retry a few times since node creation might not be immediately visible
        for attempt in range(5):
            nodes = self._list_nodes()
            for node_id, props in nodes.items():
                if props.get("node.name") == node_name:
                    return node_id
            if attempt < 4:
                time.sleep(0.05)
        raise RuntimeError(f"Could not find node with name '{node_name}'")

    def _destroy_node(self, node_id: int | None) -> bool:
        if node_id is None:
            return False
        try:
            self._run_pw_cli(["destroy", str(node_id)])
            return True
        except RuntimeError:
            return False

    def _run_pw_cli(self, args: list[str]) -> str:
        if not self._pw_cli_path:
            raise RuntimeError("pw-cli is not available")
        LOGGER.info("Running pw-cli command: $ pw-cli {}", shlex.join(args))
        try:
            result = subprocess.run(
                [self._pw_cli_path, *args],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"pw-cli {args[0] if args else 'command'} failed: {message}") from exc
        return result.stdout

    def _run_pw_dump(self) -> str:
        if not self._pw_dump_path:
            raise RuntimeError("pw-dump is not available")
        LOGGER.debug("Running pw-dump command: $ pw-dump")
        try:
            result = subprocess.run(
                [self._pw_dump_path],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"pw-dump failed: {message}") from exc
        return result.stdout
