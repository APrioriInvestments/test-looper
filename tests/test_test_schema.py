"""Golden-path tests for CommitTestDefinition."""

import object_database.web.cells as cells
import pytest

from testlooper.schema.schema import engine_schema, repo_schema, test_schema

from .utils import clear_branch_structure, generate_branch_structure, testlooper_db

testlooper_db = testlooper_db  # necessary to avoid flake8 errors

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
        timeout:
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'not docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    pytest-docker:
        kind: unit
        environment: linux-native
        dependencies:
        timeout:
        list-tests: |
            .testlooper/collect-pytest-tests.sh -m 'docker'
        run-tests: |
            .testlooper/run-pytest-tests.sh

    matlab:
        kind: unit
        environment: linux-native
        dependencies:
        timeout:
        list-tests: |
            .testlooper/collect-matlab-tests.sh
        run-tests: |
            .testlooper/run-matlab-tests.sh
"""


@pytest.mark.docker  # marking solely used to test the collection script
def test_commit_test_definition_can_generate_example_plan(testlooper_db):
    """Ensure that the example test plan from the docs is properly parsed."""
    branches = {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.transaction():
        cells.ensureSubscribedSchema(test_schema)
        commit = repo_schema.Commit.lookupUnique(hash="a")
        task = engine_schema.TestPlanGenerationTask.create(commit=commit)
        test_plan = test_schema.TestPlan(plan=TEST_PLAN, commit=commit)
        _ = engine_schema.TestPlanGenerationResult(commit=commit, data=test_plan, task=task)
        commit_test_definition = test_schema.CommitTestDefinition(commit=commit)
        commit_test_definition.set_test_plan(test_plan)

    clear_branch_structure(db=testlooper_db)
