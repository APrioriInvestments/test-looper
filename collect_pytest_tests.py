"""
Runs pytest collection and format the results.

Passes any arguments to pytest.
"""

import argparse
import subprocess
import sys

import yaml


def run_pytest_collect(args) -> str:
    """Run custom collection that includes markers.

    Normal collection only uses the test names. In order to get
    tests/ in the PYTHONPATH, and use our collector plugin,
    we must call using python -m pytest.
    """
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "tests.marker_collector_plugin",
        "--collect-tests-and-markers",
        "-q",
    ] + args
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        output = e.output
        print(f"Error occurred: {e}")
    return output


def parse_to_yaml(pytest_output: str, suite_name: str) -> str:
    """
    Convert the pytest output into yaml of the form:
    suite_name:
    - unique_test_name:
        path: str
        labels: List[str]
    """

    output = [line.strip().split("::") for line in pytest_output.split("\n")[:-4]]
    parsed_output = {suite_name: []}
    for path, name, markers in output:
        if markers:
            parsed_output[suite_name].append({name: {"path": path, "labels": markers.split("|")}})
        else:
            parsed_output[suite_name].append({name: {"path": path, "labels": markers.split("|")}})
    return yaml.dump(parsed_output)


def main():
    parser = argparse.ArgumentParser(
        description="Run pytest --collect-only and format the output to YAML."
    )
    parser.add_argument("suite_name", help="Name of the test suite")
    parser.add_argument(
        "pytest_args", nargs=argparse.REMAINDER, help="Additional arguments to pass to pytest"
    )
    args = parser.parse_args()

    output = run_pytest_collect(args.pytest_args)
    parsed_output = parse_to_yaml(output, args.suite_name)
    print(parsed_output)


if __name__ == "__main__":
    main()
