from .schema_declarations import test_schema, engine_schema, repo_schema


TaskStatus = str  # Figure out our state machine states here


@engine_schema.define
class TestPlanGenerationTask:
    """Keep track of a task to generate a test plan."""

    commit = repo_schema.Commit
    status = TaskStatus


@engine_schema.define
class TestSuiteGenerationTask:
    test_suite = test_schema.TestSuite
    status = TaskStatus


@engine_schema.define
class TestRunTask:
    test_results = test_schema.TestResults
    status = TaskStatus
