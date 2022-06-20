# The TestRunner class provides methods for running tests
# capturing and processing output

import os
import json
import subprocess


class TestRunner:
    """
    Run the tests for a given repo (excluding repo dependencies)
    """

    def __init__(self, repo_dir: str, runner_file_name='test_looper.json'):
        self.runner_file = os.path.join(repo_dir, runner_file_name)
        self._test_commands = None

    @property
    def test_commands(self):
        if self._test_commands is None:
            self.setup()
        return self._test_commands

    def setup(self):
        """
        I read in the test commands from self.runner_file
        and setup capture of test output
        """
        if not os.path.isfile(self.runner_file):
            raise FileNotFoundError(
                f"Test runner file {self.runner_file} not found: exiting!"
            )
        command_data = json.loads(open(self.runner_file).read())
        self._test_commands = command_data["test_commands"]

    def run(self):
        for command in self.test_commands:
            _run_command(command["command"], command["args"])


def _run_command(command: str, args: list[str]):
    popen_args = [command]
    popen_args.extend(args)
    with subprocess.Popen(
            popen_args,
            stdout=subprocess.PIPE, bufsize=1,
            universal_newlines=True) as p:
        for line in p.stdout:
            # TODO: capture this stdout and do something
            # useful with it
            print(line, end="")
