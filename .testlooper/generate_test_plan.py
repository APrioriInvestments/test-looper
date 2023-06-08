"""generate_test_plan.py

Currently returns a static YAML file.
"""
import argparse


TEST_PLAN = """
version: 1
environments:
    # linux docker container for running our pytest unit-tests
    linux-pytest:
        image:
            docker:
                dockerfile: .testlooper/environments/linux-pytest/Dockerfile
        variables:
            PYTHONPATH: ${REPO_ROOT}
            TP_COMPILER_CACHE: /tp_compiler_cache
            IS_TESTLOOPER: true
        min-ram-gb: 10
        custom-setup: |
            python -m pip install --editable .

    # native linux image necessary for running unit-tests that need to boot docker containers.
    linux-native:
        image:
            base_ami: ami-0XXXXXXXXXXXXXXXX  # ubuntu-20.04-ami
        min-ram-gb: 10
        custom-setup: |
            sudo apt-get --yes install python3.8-venv
            make install  # install pinned dependencies
builds:
    # skip

suites:
    pytest:
        kind: unit
        environment: linux-pytest
        dependencies:
        list-tests: |
            python .testlooper/collect_pytest_tests.py -m 'not docker'
        run-tests: |
            python .testlooper/run_pytest_tests.py -m 'not docker'
        timeout:

    pytest-docker:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            python .testlooper/collect_pytest_tests.py -m 'docker'
        run-tests: |
            python .testlooper/run_pytest_tests.py  -m 'docker'
        timeout:

    matlab:
        kind: unit
        environment: linux-native
        dependencies:
        list-tests: |
            .testlooper/collect_matlab_tests.sh
        run-tests: |
            .testlooper/run_matlab_tests.sh
        timeout:
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a test plan.")
    parser.add_argument("--output", type=str, default="test_plan.yaml")
    args = parser.parse_args()

    with open(args.output, "w") as f:
        f.write(TEST_PLAN)
