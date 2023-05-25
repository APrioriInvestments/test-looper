import click
import os
import sys

from testlooper.cli.util import ClickContext


@click.group()
@click.option(
    "-p",
    "--path",
    default=os.getcwd(),
    show_default=True,
    type=str,
    help="Specify the path to a git repo",
)
@click.pass_context
def git(ctx, path):
    """Perform operations on a local Git repo."""
    cc = ClickContext(ctx)

    if not os.path.isdir(path):
        click.secho(f"Git repo path '{path}' does not exist", fg="red")
        sys.exit(1)

    if cc.verbosity >= 3:
        click.secho(f"INFO: Git repo path: {path}", fg="green")

    cc.git_path = path


@git.command()
@click.pass_context
def gen_test_plan(ctx):
    """Generate the test-plan for a local Git repo."""
    pass
