# Repo Configuration Specification

## Design principles:

    1. maximal flexibility. you should be able to run pretty much anything that runs in a
        docker container to perform any of these steps. This is not at all python specific.
    2. no fancy sublanguages - configuration complexity should come out of scripts
    3. want to support a variety of possible test modes going from batch jobs down to granular
        individual tests, perf tests, etc.


## Spec for TL:

1. you have to specify the 'configuration' docker image or container. This is the container
    we load, along with your codebase, to actually find out what tests we're going to have.
2. you specify a "test plan program" which we invoke in the configuration container. This
    will produce a .yaml or .json file that defines the actual test plan.



Entrypoint is still this file that has to be somewhere in the repo:

`.testlooper/config.yaml`:
```
version: X.Y
os: linux
variables:
    ENV_VAR_NAME: value
    ...

image:
    # one of several ways to define the image in which we're going to run.
    aws-ami: some AWS AMI name
    docker:
        image: some docker image e.g., dockerhub.private-org.com:5000/testlooper:4589c1d02
        dockerfile: relative in-repo path to dockerfile or to directory containing a 'Dockerfile'
        with-docker: bool  # Whether we should mount the docker service socket.


generate-test-plan: |
    # Some bash code to run that produces the actual test-suite definitions and environments.
    # We can assume we have defined the following environment variables:
    #   - REPO_ROOT: path to the current checked out repo, which will also be the CWD
    #   - TEST_PLAN_OUTPUT: path to where we expect the produced test plan to go
```
Example:
```
version: 1.0
image:
     docker:
        dockerfile: .testlooper/environments/plan-generation/Dockerfile
        with-docker: true

variables:
    PYTHONPATH: ${REPO_ROOT}

command:
    python .testlooper/generate_test_plan.py  --out ${TEST_PLAN_OUTPUT}
```

test outputs are expected to define the following things, in addition to a version number (1 as of
5/17/23)

1. Environments 
2. Builds
3. Tests

An environment specifies the context in which a build or a test runs (OS, installed libraries, environment variables)

```
environments:
    environment_name:
        image:  # aws-ami | docker
        variables:
            VAR1: Value1
            VAR2: Value2
            ...
        min-ram-gb: ...
        min-cores: ...
        custom-setup: |
            # additional bash commands to set up the environment

```

A build is a sequence of steps that builds a binary artifact that may be used by another build or test

```
builds:
    build_name:
        environment: environment_name
        dependencies:
            build_name_1: pathToWhereMounted ...
            build_name_2: pathToWhereMounted ...
        command: |
            # command to build the output
            # expects
            # REPO_ROOT - path to directory containing source
            # BUILD_OUTPUT - path to directory where we should
            #   put the build output.
```

A test  is a sequence of steps that runs one or more tests and produces results for each of the tests

```
suites:
    suite_name:
        kind: unit | perf | ...  # start by only supporting 'unit'
        environment: environment_name
        dependencies:
            build_name_1: pathToWhereMounted ...
            build_name_2: pathToWhereMounted ...

            list-tests: |
                # bash command that lists individual tests
                # REPO_ROOT - path to the current checked out repo, which will also be the CWD
                # TEST_LIST - path to where we expect the output to go

            run-tests: |
                # bash command that executes individual tests given a list of test names
                # (We could either pass a file with this list or pass the list explicitly on the
                # command line to the runner-script.)
                # REPO_ROOT - path to the current checked out repo, which will also be the CWD
                # TEST_INPUT - path to a text file with the names of the tests to run.
                    If not set, run all tests in the suite.
                # TEST_OUTPUT - path to where we expect the output to go
                #       flesh this out - how do we describe which tests we ran?
                #       how do we describe where the logfiles for each test went
                #       what other metadata can each test provide?

            timeout: ... (seconds)

```

Examples:
```
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
```

```
suites:
    pytest:
        kind: unit
        environment: linux-pytest
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'not docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    pytest-docker:
        kind: unit
        environment: linux-native
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    matlab:
        kind: unit
        environment: linux-native
        list-tests: |
            .testlooper/collect-matlab-tests.sh
        run-tests: |
            .testlooper/run-matlab-tests.sh
```

### Format for the output of list-tests

```
suite_name:
  - unique_test_name:
    path: str  # do we need this?
    labels: List[str]  # e.g., pytest markings such as slow, skip, docker
```

### Format for the output of run-tests

Let's start with the format of pytest-json-report:
https://pypi.org/project/pytest-json-report/#format
