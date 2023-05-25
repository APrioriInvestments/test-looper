import click
import os

from .util import ClickContext
from .git.git import git


@click.group()
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase Verbosity. Use mupliple times to increase verbosity, e.g., -vvv.",
)
@click.option(
    "-q",
    "--quiet",
    count=True,
    help="Decrease Verbosity. Use mupliple times to decrease verbosity, e.g., -qqq.",
)
@click.pass_context
def tlcli(ctx, verbose, quiet):
    """Test Looper Command Line Interface"""
    cc = ClickContext(ctx)

    cc.verbosity = int(os.getenv("APCTL_VERBOSITY", 0)) + verbose - quiet

    if cc.verbosity >= 5:
        click.secho(f"INFO: Verbosity Level: {cc.verbosity}", fg="green")


tlcli.add_command(git)
