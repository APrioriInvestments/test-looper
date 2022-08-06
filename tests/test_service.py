from pathlib import Path
from urllib.parse import urlparse

from object_database.database_connection import DatabaseConnection
import pytest

from test_looper.git import GIT, Repo
from test_looper.service import (
    LooperService,
    parse_repo_url,
    parse_commits,
    parse_branch,
)
from test_looper.service_schema import Config, ArtifactStorageConfig
from test_looper.repo_schema import Repository, RepoConfig, Commit, Branch
from conftest import odb_conn


@pytest.fixture(scope="module")
def tl_config(
    odb_conn: DatabaseConnection, tmp_path_factory: pytest.TempPathFactory
) -> dict:
    """
    Create a test looper service Config and clean it up after we're done
    """
    tmp_path = tmp_path_factory.mktemp("odb")
    storage = ArtifactStorageConfig.LocalDisk(
        build_artifact_path=str(tmp_path / "build"),
        test_artifact_path=str(tmp_path / "test"),
    )
    dd = dict(
        repo_url=str(tmp_path / "repos"),
        temp_url=str(tmp_path / "tmp"),
        artifact_store=storage,
    )
    with odb_conn.transaction():
        config = Config(**dd)
    yield dd
    with odb_conn.transaction():
        config = Config.lookupUnique()
        config.delete()


def test_create_service(odb_conn: DatabaseConnection, tl_config):
    service = LooperService.from_odb(odb_conn)
    assert service.repo_url == tl_config["repo_url"]
    assert service.temp_url == tl_config["temp_url"]
    assert service.artifact_store == tl_config["artifact_store"]


def test_add_repo(odb_conn: DatabaseConnection, tl_config):
    service = LooperService.from_odb(odb_conn)
    # TODO test the FromService variant
    # test_parse_repo tests adding the other types
    repos = {
        "test-looper": "https://github.com/aprioriinvestments/test-looper",
        "typed_python": "https://github.com/aprioriinvestments/typed_python",
        "odb": "https://github.com/aprioriinvestments/object_database",
    }
    for name, url in repos.items():
        service.add_repo(name, url)
    all_repos = service.get_all_repos()
    for name, config in all_repos.items():
        assert repos[name] == config.url

    for name, url in repos.items():
        config = service.get_repo_config(name)
        assert isinstance(config, RepoConfig.Https)
        assert config.url == url


def test_clone_repo(odb_conn: DatabaseConnection, tl_config):
    service = LooperService.from_odb(odb_conn)
    name = "test-looper"
    config = service.add_repo(
        name, "https://github.com/aprioriinvestments/test-looper"
    )
    clone_name, clone_config = service.clone_repo(name, clone_name="clone")
    assert clone_name == "clone"
    assert isinstance(clone_config, RepoConfig.Local)
    assert clone_config.path == f"{service.repo_url}/clone"
    remote_name, remote_config = service.get_remote(clone_name)
    assert remote_name == name
    assert remote_config == config


def test_parse_repo():
    alternatives = [
        (RepoConfig.Ssh, "ssh://user@foo.com:org/repo", {"private_key": b""}),
        (RepoConfig.Ssh, "git@github.com:org/repo", {"private_key": b""}),
        (RepoConfig.Https, "https://github.com/org/repo", {}),
        (RepoConfig.Local, "file:///path/to/repo", {}),
        (RepoConfig.Local, "/path/to/repo", {}),
        (RepoConfig.S3, "s3://bucket/path/to/repo", {}),
    ]
    for i, (klass, conf_str, kwargs) in enumerate(alternatives):
        _check_str_repo_config(klass, f"tl-{i}", conf_str, **kwargs)


def test_parse_commit(odb_conn: DatabaseConnection, tl_repo: Repo):
    head = tl_repo.head.commit
    conf = RepoConfig.Local(tl_repo.working_dir)
    with odb_conn.transaction():
        repo = Repository(config=conf, name="test_parse_commit")
        parse_commits(repo, head)
        _check_tree(head, Commit.lookupOne(sha=head.hexsha))


def test_parse_branch(odb_conn: DatabaseConnection, tl_repo: Repo):
    conf = RepoConfig.Local(tl_repo.working_dir)
    with odb_conn.transaction():
        repo = Repository(config=conf, name="test_parse_branch")
        for branch in tl_repo.heads:
            parse_branch(repo, branch)
            _check_tree(
                branch.commit, Commit.lookupOne(sha=branch.commit.hexsha)
            )


def test_scan_repo(odb_conn: DatabaseConnection):
    service = LooperService.from_odb(odb_conn)
    service.add_repo(
        "test-looper", "https://github.com/aprioriinvestments/test-looper"
    )
    (name, clone_conf) = service.clone_repo(
        "test-looper", clone_name="test_scan_repo"
    )
    service.scan_repo("test_scan_repo", branch="*")
    with service.db.view():
        repo = Repository.lookupOne(name=name)
        for b in GIT().list_branches(clone_conf.path):
            odb_branch = Branch.lookupOne(repoAndName=(repo, b.name))
            assert b.commit.hexsha == odb_branch.top_commit.sha


def _check_tree(expected, odb_results):
    assert expected.hexsha == odb_results.sha
    expected_parents = expected.parents
    odb_parents = odb_results.parents
    assert len(expected_parents) == len(odb_parents)
    for git, odb in zip(
        sorted(expected_parents, key=lambda x: x.hexsha),
        sorted(odb_parents, key=lambda x: x.sha),
    ):
        _check_tree(git, odb)


@pytest.fixture(scope="module")
def tl_repo(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("repo")
    repo = "https://github.com/aprioriinvestments/test-looper"
    clone_to = str(tmp_path / "test_looper")
    GIT().clone(repo, clone_to, all_branches=True)
    return Repo(clone_to)


def _check_str_repo_config(klass, name, url, **kwargs):
    config = parse_repo_url(url, **kwargs)
    assert isinstance(config, klass)
    if klass == RepoConfig.Local:
        assert config.path == urlparse(url).path
    else:
        assert config.url == url