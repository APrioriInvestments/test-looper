import click
import os
import subprocess
import sys
import yaml

from testlooper.cli.util import ClickContext

DEFAULT_TEST_PLAN_OUTPUT = ".testlooper/test_plan.yaml"


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


@click.option(
    "-c",
    "--config",
    default=".testlooper/config.yaml",
    show_default=True,
    type=click.Path(exists=True),
    help="Specify the path to a testlooper config YAML file",
)
@click.option(
    "--test-plan-output",
    default=os.environ.get("TEST_PLAN_OUTPUT"),
    help="Path to output the generated test plan",
)
@git.command()
@click.pass_context
def gen_test_plan(ctx, config, test_plan_output):
    """Generate the test-plan for a local Git repo.

    Default config path is .testlooper/config.yaml.
    Default test plan output is $TEST_PLAN_OUTPUT, or .testlooper/test_plan.yaml if no
    such environment variable is set.
    """
    cc = ClickContext(ctx)
    if test_plan_output is None:
        test_plan_output = os.path.join(cc.git_path, DEFAULT_TEST_PLAN_OUTPUT)

    if cc.verbosity >= 3:
        click.secho(f"INFO: Testlooper config path: {config}", fg="green")
        click.secho(f"INFO: Test plan output path: {test_plan_output}", fg="green")

    with open(config, "r") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            click.secho(f"ERROR: Couldn't parse YAML file: {e}", fg="red")
            sys.exit(1)

    command = data.get("command")
    if command is None:
        click.secho("ERROR: No command specified in config file", fg="red")
        sys.exit(1)

    env = os.environ.copy()
    env["TEST_PLAN_OUTPUT"] = test_plan_output

    subprocess.run(command, shell=True, cwd=cc.git_path, env=env)
