#!/usr/bin/env python
"""
Runs pytest and generates a json report.

Passes any arguments to pytest.
"""

import subprocess
import sys

from typing import Optional


def run_pytest_json_report(args) -> Optional[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--json-report",
    ] + args
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        output = e.output
        print(f"Error occurred: {e}")
        return None
    return output


def main():
    # TODO specify where the report goes.
    args = sys.argv[1:]
    output = run_pytest_json_report(args)
    print(output)


if __name__ == "__main__":
    main()
