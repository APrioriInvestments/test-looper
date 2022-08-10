"""Test the test parser"""
import hashlib
import pytest
from object_database.database_connection import DatabaseConnection

from test_looper.parser import TestParserService
from test_looper.repo_schema import Commit, RepoConfig, Repository
from test_looper.service import LooperService
from test_looper.test_schema import TestNode


@pytest.fixture
def parser_service(odb_conn: DatabaseConnection,
                   tl_config: dict) -> TestParserService:
    setup_repo(odb_conn)
    return TestParserService(odb_conn, tl_config["repo_url"])


def setup_repo(odb_conn: DatabaseConnection):
    service = LooperService.from_odb(odb_conn)
    service.add_repo(
        "test-looper", "https://github.com//aprioriinvestments/test-looper"
    )
    service.clone_repo("test-looper", "my-test-looper-clone")
    service.scan_repo("my-test-looper-clone", branch="*")


def test_parse_commits(parser_service: TestParserService):
    with parser_service.db.view():
        assert len(TestNode.lookupAll()) == 0
    parser_service.parse_commits()
    with parser_service.db.view():
        nodes = TestNode.lookupAll()
        assert len(nodes) > 0
        test_def = nodes[0].definition
        assert test_def.runTests.bashCommand is not None


