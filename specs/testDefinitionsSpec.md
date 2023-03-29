# TestDefinitions Spec

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

`testDefinitions.yaml`:
```
image:
    # one of three ways to define the image in which we're going to run.
    ami: someAmiName
    docker_contents: text_contents
    dockerfile: path-in-repo

command: |
    # some bash code to run that produces the actual test definitions and environments
    # can assume we have defined the following environment variables:
    # TEST_SRC - path to the current checked out repo, which will also be the CWD
    # CONFIG_OUTPUT - path to where we expect the output to go
```
Example:
```
 image:
     dockerfile: fixtures/testLooperConfigDockerfile

variables:
    PYTHONPATH: ${TEST_SRC}

command:
    python -m generateTestLooperEnvironmentsAndTests.py  --out ${CONFIG_OUTPUT}
```

test outputs are expected to define the following things: 

1. Environments 
2. Builds
3. Tests

An environment specifies the context in which a build or a test runs (OS, installed libraries, environment variables)

```
environments:
    environment_name:
        image:  # ami | docker | dockerfile
        custom-setup: |
            # additional bash commands to set up the environment
        variables:
            VAR1: VAR1Val
            VAR2: VAR2Val
            ...
        min_ram_gb: ...
        min_cores: ...
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
            # TEST_SRC - path to directory containing source
            # BUILD_OUTPUT - path to directory where we should
            #   put the build output.
```

A test  is a sequence of steps that runs one or more tests and produces results for each of the tests

```
tests:
    test_name:
        environment: environment_name
        dependencies:
            build_name_1: pathToWhereMounted ...
            build_name_2: pathToWhereMounted ...

            list-tests: |
                # bash command that lists individual tests
                # TEST_SRC - path to the current checked out repo, which will also be the CWD
                # TEST_LIST - path to where we expect the output to go

            run-tests: |
                # bash command that executes individual tests given a list of test names
                # (We could either pass a file with this list or pass the list explicitly on the
                # command line to the runner-script.)
                # TEST_SRC - path to the current checked out repo, which will also be the CWD
                # TEST_INPUTS - path to a text file with the names of the tests to run
                # TEST_OUT - path to where we expect the output to go
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
        min_ram_gb: 10
        variables:
            PYTHONPATH: ${TEST_SRC}
            TP_COMPILER_CACHE: /tp_compiler_cache
            IS_TESTLOOPER: true
        image:
            dockerfile: fixtures/testLooperPytestDockerfile
        custom-setup:
            python -m pip install --editable .

    # native linux image necessary for running unit-tests that need to boot docker containers.
    linux-native:
        min_ram_gb: 10
        image:
            base_ami: ami-070b2b608b25dc0f1  # ubuntu-20.04-ami
        custom-setup: |
            sudo apt-get --yes install libgdal-dev gdal-bin python3.8-venv
            make install  # install pinned dependencies

```

```
tests:
    pytest:
        environment: linux-pytest
        list-tests: |
            ./scripts/collectPytestTests.sh -m 'not docker'
        run-tests: |
            ./scripts/runPytestTests.sh

    pytest-docker:
        environment: linux-native
        list-tests: |
            ./scripts/collectPytestTests.sh -m 'docker'
        run-tests: |
            ./scripts/runPytestTests.sh

    matlab:
        environment: linux-native
        list-tests: |
            ./scripts/collectMatlabTests.sh
        run-tests: |
            ./scripts/runMatlabTests.sh
```