"""
General Tests for Test Looper
"""
import os

# import sys
import shutil
import pytest

# from test_looper.git import GIT
from test_looper.schema import *
from test_looper.odb import OdbReporter
from test_looper.runner import TestRunner as TRunner
from test_looper.runner import TestList as TList
from test_looper.runner import TestRunnerResult as TRunnerResult

try:
    from object_database.persistence import InMemoryPersistence
    from object_database.tcp_server import TcpServer
    from object_database.util import sslContextFromCertPathOrNone
    from object_database.tcp_server import DatabaseConnection
    from object_database import connect, Schema
except ModuleNotFoundError:
    print("unable to import ODB - skipping ODB dependent tests")
# GLOBALS
repo_path = "/tmp/test_repo"
odb_server_host = "localhost"
odb_server_port = 8000
odb_server_token = "TLTESTTOKEN"


class TestTestLooper:
    def setup_class(self):
        # git = GIT()
        # create a repo where tests will run
        # status = git.clone('tests/_template_repo', repo_path)
        # if status:
        #    sys.exit("Could not clone test repo")
        # copy the a template directory "repo" with tests
        shutil.copytree("tests/_template_repo", repo_path, dirs_exist_ok=True)
        try:
            server = TcpServer(
                odb_server_host,
                odb_server_port,
                InMemoryPersistence(),
                ssl_context=sslContextFromCertPathOrNone(None),
                auth_token=odb_server_token,
            )
            server.start()
            self.server = server
        except Exception:
            print("unable to start ODB - skipping ODB dependent tests")

    @pytest.fixture(autouse=True)
    def runner(self):
        # NOTE: rename TestRunner to TRunner or pytest gets confused
        self.runner = TRunner(repo_path)

    @pytest.fixture(scope="module")
    def odb_connection(self):
        odb = connect(
            odb_server_host, odb_server_port, odb_server_token, retry=True
        )
        odb.subscribeToSchema(test_looper_schema)
        return odb

    def test_runner_setup(self):
        assert self.runner._test_commands is None
        self.runner.setup()
        assert self.runner._test_commands

    def test_runner_list(self):
        results = self.runner.list()
        # TODO: need better inspection here once tests stabilize
        assert isinstance(results[0][1]["retcode"].value, int)
        assert isinstance(results[0][1]["results"], TList)

    def test_runner_run(self):
        all_results = self.runner.run()
        # TODO: need better inspection here once tests stabilize
        command, results = all_results[0]
        assert set(command.keys()) == set(["command", "args"])
        assert isinstance(results["retcode"].value, int)
        assert isinstance(results["results"], TRunnerResult)

    def test_runner_repeat(self):
        all_results = self.runner.run()
        assert (
            len(
                [
                    item
                    for item in all_results
                    if item[0]["args"]
                    == ["tests/test.py::TestTest::test_success"]
                ]
            )
            == 3
        )

    @pytest.mark.skipif(
        odb_connection is None, reason="no ODB connection instance found"
    )
    def test_odb_empty(self, odb_connection):
        nodes = []
        with odb_connection.view():
            for n in TestNode.lookupAll():
                nodes.append(n)
            assert len(nodes) == 0

    @pytest.mark.skipif(
        odb_connection is None, reason="no ODB connection instance found"
    )
    def test_odb_lists(self, odb_connection):
        results = self.runner.list()
        reporter = OdbReporter(odb_connection)
        [
            reporter.report_tests(test_list["results"].tests)
            for command, test_list in results
        ]
        nodes = []
        with odb_connection.view():
            for n in TestNode.lookupAll():
                nodes.append(n)
            assert len(nodes) > 0

    @classmethod
    def teardown_class(self):
        if self.server:
            self.server.stop()
        os.system(f"rm -rf {repo_path}")
