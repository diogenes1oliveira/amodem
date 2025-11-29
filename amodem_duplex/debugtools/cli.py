"""CLI entry point for managing PipeWire debug pipes."""

import click

from .pipewire_pipe import PipeWirePipeManager


def _echo_pipe_info(pipe, *, prefix=""):
    click.echo(
        f"{prefix}{pipe.id} (sink={pipe.sink_name}, source={pipe.source_name})",
        err=True,
    )


@click.group()
def pw_group() -> None:
    """Manage PipeWire virtual pipes for aduplex."""


@pw_group.command()
@click.argument("name")
@click.option("--sample-rate", default=16000, show_default=True, type=int)
@click.option("--channels", default=1, show_default=True, type=int)
@click.option("--prefix", default="amodem-test-", show_default=True)
@click.option("--suffix-input", default=" Mic", show_default=True)
@click.option("--suffix-output", default=" Speaker", show_default=True)
def create(
    name: str,
    sample_rate: int,
    channels: int,
    prefix: str,
    suffix_input: str,
    suffix_output: str,
) -> None:
    """Create a PipeWire sink/source pair."""
    manager = PipeWirePipeManager(prefix=prefix, suffix_input=suffix_input, suffix_output=suffix_output)
    pipe = manager.create(name, sample_rate=sample_rate, channels=channels)
    _echo_pipe_info(pipe, prefix="Created: ")


@pw_group.command()
@click.argument("pattern", required=False)
@click.option("--prefix", default="amodem-test-", show_default=True)
def list(
    pattern: str | None,
    prefix: str,
) -> None:
    """List PipeWire pipes that match PATTERN."""
    manager = PipeWirePipeManager(prefix=prefix)
    pipes = manager.list_all(pattern)
    if not pipes:
        click.echo("No matching pipes found", err=True)
        return
    for pipe in pipes:
        _echo_pipe_info(pipe)


@pw_group.command()
@click.argument("identifier")
@click.option("--prefix", default="amodem-test-", show_default=True)
def get(identifier: str, prefix: str) -> None:
    """Show details for a single pipe."""
    manager = PipeWirePipeManager(prefix=prefix)
    pipe = manager.get(identifier)
    if pipe is None:
        click.echo(f"No pipe found for '{identifier}'", err=True)
        return
    _echo_pipe_info(pipe)


@pw_group.command()
@click.argument("identifier")
@click.option("--prefix", default="amodem-test-", show_default=True)
def delete(identifier: str, prefix: str) -> None:
    """Delete a single pipe."""
    manager = PipeWirePipeManager(prefix=prefix)
    if manager.delete(identifier):
        click.echo(f"Deleted pipe '{identifier}'", err=True)
        return
    click.echo(f"Could not delete pipe '{identifier}'", err=True)


@pw_group.command(name="delete-all")
@click.argument("pattern", required=False)
@click.option("--prefix", default="amodem-test-", show_default=True)
def delete_all(pattern: str | None, prefix: str) -> None:
    """Delete all pipes matching PATTERN."""
    manager = PipeWirePipeManager(prefix=prefix)
    if not click.confirm("Delete matching pipes?"):
        click.echo("Aborted", err=True)
        return
    deleted = manager.delete_all(pattern)
    click.echo(f"Deleted {deleted} pipes", err=True)
