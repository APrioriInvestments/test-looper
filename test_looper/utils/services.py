import pathlib
import uuid
import shutil
import git

from object_database import connect

from test_looper import test_looper_schema
from test_looper.service import LooperService
from test_looper.parser import ParserService
from test_looper.runner import RunnerService, DispatchService
from test_looper.tl_git import GIT


def init_test_repo():
    # copy template repo and turn it into a git repo
    tmp_path = pathlib.Path('/tmp') / str(uuid.uuid4())
    dst_path = str(tmp_path / '_template_repo')
    file_path = pathlib.Path(__file__)
    git_repo = git.Repo(file_path, search_parent_directories=True)
    repo_root = git_repo.git.rev_parse("--show-toplevel")

    repo = str(pathlib.Path(repo_root, "tests/_template_repo"))
    shutil.copytree(repo, dst_path)
    GIT().init_repo(dst_path)
    return dst_path


def run_tests(host, port, token):
    repo_path = init_test_repo()
    odb = connect(host, port, token)
    odb.subscribeToSchema(test_looper_schema)

    # the idea here is that these different services
    # implement their own event loops and could run
    # in a distributed fashion as long as they're
    # all interacting with the same ODB

    # Register a repo and scan all branches for commits
    looper = LooperService(odb)
    looper.add_repo('template_repo', repo_path)
    looper.scan_repo('template_repo', branch="*")

    # Parse commits and create test plan
    parser = ParserService(odb)
    parser.parse_commits()

    # create a dispatcher to assign TestNodes
    dispatch = DispatchService(odb)
    # register a worker
    runner = RunnerService(odb, "tout seul")

    dispatch.assign_nodes()  # this will assign it to the runner
    runner.run_test()
    return odb
