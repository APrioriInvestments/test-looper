#!/usr/bin/env python3

import sys
import tempfile
import time

from object_database.service_manager.ServiceManager import ServiceManager
from object_database import connect, core_schema, service_schema
from object_database.frontends.service_manager import startServiceManagerProcess

from test_looper.parser import ParserService
from test_looper.runner import RunnerService


def main(service_classes, run_db=False):
    odb_token = "TOKEN"
    odb_host = "localhost"
    odb_port = 8080
    loglevel_name = "INFO"

    with tempfile.TemporaryDirectory() as tmpDirName:
        server = None
        try:
            server = startServiceManagerProcess(
                tmpDirName, odb_port, odb_token, loglevelName=loglevel_name,
                logDir=False, runDb=run_db
            )

            database = connect(odb_host, odb_port, odb_token, retry=True)
            database.subscribeToSchema(core_schema, service_schema)

            with database.transaction():
                for s in service_classes:
                    ServiceManager.createOrUpdateService(
                        s, s.__name__, target_count=0
                    )

            for s in service_classes:
                with database.transaction():
                    ServiceManager.startService(s.__name__, 1)

            while True:
                time.sleep(0.1)
        finally:
            if server is not None:
                server.terminate()
                server.wait()

    return 0


if __name__ == "__main__":
    sys.exit(main([ParserService, RunnerService], run_db=True))
