# The TestRunner class provides methods for running tests
# capturing and processing output

import os
import json
import subprocess


class TestRunner:
    def __init__(self, runner_file_name="test_looper.json"):
        # we are assuming that the runner file is located at the root
        # of the repository
        self.runner_file = os.path.join(
            os.environ["TEST_LOOPER_ROOT"],
            runner_file_name
            )
        self.test_commands = []

    def setup(self):
        """
        I read in the test commands from self.runner_file
        and setup capture of test output
        """
        if not os.path.isfile(self.runner_file):
            raise FileNotFoundError(
                "Test runner file %s not found: exiting!" % (self.runner_file)
            )
        command_data = json.loads(open(self.runner_file).read())
        self.test_commands = command_data["test_commands"]

    def run(self):
        for command in self.test_commands:
            with subprocess.Popen(
                    [command["command"]] + command["args"],
                    stdout=subprocess.PIPE, bufsize=1,
                    universal_newlines=True) as p:
                for line in p.stdout:
                    # TODO: capture this stdout and do something
                    # useful with it
                    print(line, end="")

            # if p.returncode != 0:
            #    raise subprocess.CalledProcessError(p.returncode, p.args)
