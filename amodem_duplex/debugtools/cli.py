"""CLI entry point for managing PulseAudio debug pipes."""

import click

from .pulseaudio_pipe import PulseAudioPipeManager


def _echo_pipe_info(pipe, *, prefix=""):
    click.echo(
        f"{prefix}{pipe.id} (sink={pipe.sink_name}, source={pipe.source_name})",
        err=True,
    )


@click.group()
def pa_group() -> None:
    """Manage PulseAudio virtual pipes for aduplex."""


@pa_group.command()
@click.argument("name")
@click.option("--sample-rate", default=16000, show_default=True, type=int)
@click.option("--channels", default=1, show_default=True, type=int)
@click.option("--prefix", default="amodem-test", show_default=True)
@click.option("--suffix-input", default="mic", show_default=True)
@click.option("--suffix-output", default="speaker", show_default=True)
def create(
    name: str,
    sample_rate: int,
    channels: int,
    prefix: str,
    suffix_input: str,
    suffix_output: str,
) -> None:
    """Create a PulseAudio sink/source pair."""
    manager = PulseAudioPipeManager(prefix=prefix, suffix_input=suffix_input, suffix_output=suffix_output)
    pipe = manager.create(name, sample_rate=sample_rate, channels=channels)
    _echo_pipe_info(pipe, prefix="Created: ")


@pa_group.command()
@click.argument("pattern", required=False)
@click.option("--prefix", default="amodem-test", show_default=True)
def list(
    pattern: str | None,
    prefix: str,
) -> None:
    """List PulseAudio pipes that match PATTERN."""
    manager = PulseAudioPipeManager(prefix=prefix)
    pipes = manager.list_all(pattern)
    if not pipes:
        click.echo("No matching pipes found", err=True)
        return
    for pipe in pipes:
        _echo_pipe_info(pipe)


@pa_group.command()
@click.argument("identifier")
@click.option("--prefix", default="amodem-test", show_default=True)
def get(identifier: str, prefix: str) -> None:
    """Show details for a single pipe."""
    manager = PulseAudioPipeManager(prefix=prefix)
    pipe = manager.get(identifier)
    if pipe is None:
        click.echo(f"No pipe found for '{identifier}'", err=True)
        return
    _echo_pipe_info(pipe)


@pa_group.command()
@click.argument("identifier")
@click.option("--prefix", default="amodem-test", show_default=True)
def delete(identifier: str, prefix: str) -> None:
    """Delete a single pipe."""
    manager = PulseAudioPipeManager(prefix=prefix)
    if manager.delete(identifier):
        click.echo(f"Deleted pipe '{identifier}'", err=True)
        return
    click.echo(f"Could not delete pipe '{identifier}'", err=True)


@pa_group.command(name="delete-all")
@click.argument("pattern", required=False)
@click.option("--prefix", default="amodem-test", show_default=True)
def delete_all(pattern: str | None, prefix: str) -> None:
    """Delete all pipes matching PATTERN."""
    manager = PulseAudioPipeManager(prefix=prefix)
    if not click.confirm("Delete matching pipes?"):
        click.echo("Aborted", err=True)
        return
    deleted = manager.delete_all(pattern)
    click.echo(f"Deleted {deleted} pipes", err=True)
