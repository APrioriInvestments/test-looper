import os
import pytest
import shutil

from object_database.persistence import InMemoryPersistence
from object_database.tcp_server import TcpServer, connect, DatabaseConnection
from object_database.util import sslContextFromCertPathOrNone

from test_looper import test_looper_schema

# TODO read this from test configuration file
TL_ODB_HOST = "localhost"
TL_ODB_PORT = 8000
TL_ODB_TOKEN = "TLTESTTOKEN"


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="module")
def odb_conn(odb_server: TcpServer) -> DatabaseConnection:
    conn = connect(TL_ODB_HOST, TL_ODB_PORT, TL_ODB_TOKEN, retry=True)
    conn.subscribeToSchema(test_looper_schema)
    yield conn
    conn.disconnect(block=True)
