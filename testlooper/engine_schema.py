from object_database import Indexed
from .schema_declarations import test_schema, engine_schema, repo_schema


TaskStatus = str  # Figure out our state machine states here


@engine_schema.define
class TestPlanGenerationTask:
    """Keep track of a task to generate a test plan."""

    commit = Indexed(repo_schema.Commit)
    status = TaskStatus


@engine_schema.define
class TestSuiteGenerationTask:
    commit = Indexed(repo_schema.Commit)
    name = str
    test_suite = test_schema.TestSuite
    status = TaskStatus


@engine_schema.define
class TestRunTask:
    test_results = test_schema.TestResults
    status = TaskStatus
