from pathlib import Path
from urllib.parse import urlparse

from object_database.database_connection import DatabaseConnection
import pytest

from test_looper.service import LooperService, parse_repo_url
from test_looper.service_schema import Config, ArtifactStorageConfig
from test_looper.repo_schema import Repository, RepoConfig
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
        with service.add_repo(name, url) as repo:
            assert repo.name == name
            assert repo.config.url == url

    all_repos = service.get_all_repos()
    for name, config in all_repos.items():
        assert repos[name] == config.url

    for name, url in repos.items():
        config = service.get_repo_config(name)
        assert isinstance(config, RepoConfig.Https)
        assert config.url == url


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


def _check_str_repo_config(klass, name, url, **kwargs):
    config = parse_repo_url(url, **kwargs)
    assert isinstance(config, klass)
    if klass == RepoConfig.Local:
        assert config.path == urlparse(url).path
    else:
        assert config.url == url
