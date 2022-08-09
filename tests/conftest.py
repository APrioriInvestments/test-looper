import os
import pytest
import shutil

from object_database.persistence import InMemoryPersistence
from object_database.tcp_server import TcpServer, connect, DatabaseConnection
from object_database.util import sslContextFromCertPathOrNone

from test_looper import test_looper_schema

# TODO read this from test configuration file
from test_looper.service_schema import ArtifactStorageConfig, Config

TL_ODB_HOST = "localhost"
TL_ODB_PORT = 8000
TL_ODB_TOKEN = "TLTESTTOKEN"


@pytest.fixture()
def odb_server() -> TcpServer:
    server = TcpServer(
        TL_ODB_HOST,
        TL_ODB_PORT,
        InMemoryPersistence(),
        ssl_context=sslContextFromCertPathOrNone(None),
        auth_token=TL_ODB_TOKEN,
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture()
def odb_conn(odb_server: TcpServer) -> DatabaseConnection:
    conn = connect(TL_ODB_HOST, TL_ODB_PORT, TL_ODB_TOKEN, retry=True)
    conn.subscribeToSchema(test_looper_schema)
    yield conn
    conn.disconnect(block=True)


@pytest.fixture()
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
