from pathlib import Path
import pytest

from object_database.database_connection import DatabaseConnection

from test_looper.service import LooperService
from test_looper.service_schema import Config, ArtifactStorageConfig
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
