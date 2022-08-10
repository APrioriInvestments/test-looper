"""Test the test parser"""
import pathlib
import pytest
from object_database.database_connection import DatabaseConnection
import shutil

from test_looper.parser import ParserService
from test_looper.service import LooperService
from test_looper.test_schema import TestNode as TNode
from test_looper.tl_git import GIT


@pytest.fixture
def template_repo(tmp_path):
    dst_path = str(tmp_path / '_template_repo')
    repo = str(pathlib.Path(__file__).parent / "_template_repo")
    shutil.copytree(repo, dst_path)
    GIT().init_repo(dst_path)
    return dst_path


@pytest.fixture
def parser_service(odb_conn: DatabaseConnection,
                   template_repo: str,
                   tl_config: dict) -> ParserService:
    setup_repo(odb_conn, template_repo)
    return ParserService(odb_conn)


def setup_repo(odb_conn: DatabaseConnection, template_repo: str):
    service = LooperService.from_odb(odb_conn)
    service.add_repo(
        "_template_repo", template_repo
    )
    service.scan_repo("_template_repo", branch="*")


def test_parse_commits(parser_service: ParserService):
    with parser_service.db.view():
        assert len(TNode.lookupAll()) == 0
    parser_service.parse_commits()
    with parser_service.db.view():
        nodes = TNode.lookupAll()
        assert len(nodes) > 0
        test_def = nodes[0].definition
        assert test_def.runTests.bashCommand is not None
