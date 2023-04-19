from typed_python import OneOf, Alternative, TupleOf, Dict, NamedTuple
from object_database import Schema, Indexed, Index, SubscribeLazilyByDefault

# schema for test-looper test objects
test_schema = Schema("test_looper_test")


@test_schema.define
class TestPlan:
    commit = Indexed(repo_schema.Commit)

    plan = str  # YAML file contents


@test_schema.define
class TestSuite:
    commit = Indexed(repo_schema.Commit)
    name = str  # perhaps Indexed

    tests = TupleOf(test_schema.Test)


@test_schema.define
class Test:
    commit = Indexed(repo_schema.Commit)
    name = str  # perhaps Indexed
    labels = TupleOf(str)
