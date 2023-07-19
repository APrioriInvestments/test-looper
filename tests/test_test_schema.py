"""Golden-path tests for CommitTestDefinition."""
import pytest

from testlooper.schema.schema import engine_schema, repo_schema, test_schema

from .utils import clear_branch_structure, generate_branch_structure, testlooper_db, TEST_PLAN

testlooper_db = testlooper_db  # necessary to avoid flake8 errors


@pytest.mark.docker  # marking solely used to test the collection script
def test_commit_test_definition_can_generate_example_plan(testlooper_db):
    """Ensure that the example test plan from the docs is properly parsed."""
    branches = {"dev": ["a", "b", "c"], "feature": ["a", "d", "e"]}
    generate_branch_structure(db=testlooper_db, branches=branches)

    with testlooper_db.transaction():
        commit = repo_schema.Commit.lookupUnique(hash="a")
        task = engine_schema.TestPlanGenerationTask.create(commit=commit)
        test_plan = test_schema.TestPlan(plan=TEST_PLAN, commit=commit)
        _ = engine_schema.TestPlanGenerationResult(commit=commit, data=test_plan, task=task)
        commit_test_definition = test_schema.CommitTestDefinition(commit=commit)
        commit_test_definition.set_test_plan(test_plan)

    clear_branch_structure(db=testlooper_db)
