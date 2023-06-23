#!/usr/bin/env python
"""
Runs pytest and generates a json report.

Passes any arguments to pytest.
"""
import os
import subprocess
import sys
from typing import Optional


def run_pytest_json_report(args) -> Optional[str]:
    test_output = os.environ.get("TEST_OUTPUT")
    test_input = os.environ.get("TEST_INPUT")

    command = [sys.executable, "-m", "pytest", "--json-report"]

    if test_output:
        command.extend(["--json-report-file", test_output])

    if test_input:
        # we expect a test on each line, with the format path_to_file::test_name
        with open(test_input, "r") as flines:
            test_cases = [
                line.strip()
                for line in flines.readlines()
                if line and not line.startswith("#")
            ]
        command.extend(test_cases)

    command.extend(args)
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        output = e.output
        print(f"Error occurred: {e}")
        return None
    return output


def main():
    args = sys.argv[1:]
    output = run_pytest_json_report(args)
    print(output)


if __name__ == "__main__":
    main()
