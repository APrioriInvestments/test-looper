"""git_watcher_service.py

Follows the structure of ActiveWebService to accept POST requests from
a local/GitHub/GitLab webhook and update ODB accordingly.
"""

import logging

import object_database.web.cells as cells
from flask import Flask, request
from gevent.pywsgi import WSGIServer
from object_database import ServiceBase

from testlooper.utils import setup_logger
from testlooper.schema.schema import engine_schema


class GitWatcherService(ServiceBase):
    """Listens for POST requests, generates ODB objects (and maybe Tasks)"""

    def initialize(self):
        self.db.subscribeToSchema(engine_schema)
        self._logger = setup_logger(__name__, level=logging.INFO)
        self.app = Flask(__name__)
        self.app.add_url_rule(
            "/git_updater", view_func=self.catch_git_change, methods=["POST"]
        )
        # self.app.errorhandler(WebServiceError)(self.handleWebServiceError)

    def doWork(self, shouldStop):
        """Spins up a WSGI server. Needs a GitWatcherConfig to have been created."""
        while not shouldStop.is_set():
            try:
                with self.db.view():
                    config = engine_schema.GitWatcherConfig.lookupUnique(
                        service=self.serviceObject
                    )
                    if config is None:
                        raise RuntimeError(f"No config found for service {self.serviceObject}")
                    self._logger.setLevel(config.log_level)
                    host = config.hostname
                    port = config.port
                self._logger.info("Starting Git Watcher Service on %s:%s" % (host, port))
                server = WSGIServer((host, port), self.app)
                server.serve_forever()
            except Exception as e:
                shouldStop.set()
                self._logger.error(str(e))

    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        return cells.Card(cells.Text("Git Watcher Service"))

    def catch_git_change(self):
        """Called when we get a POST request."""
        self._logger.warning("Git change caught!")
        data = request.get_json()
        if not data:
            self._logger.warning("Bad request")
            return {
                "message": "Bad Request",
                "details": "No data provided or not JSON format",
            }, 400
        try:
            self._logger.info('Received data: "%s"' % data)
            message = "ODB updated successfully"
            self._logger.info(message)
            return {"message": message}, 201
        except Exception as e:
            self._logger.exception(e)
            return {"message": "Internal Server Error", "details": str(e)}, 500

    @staticmethod
    def configure(db, service_object, hostname, port, level_name="INFO"):
        """Gets or creats a Configuration ODB object, sets the hostname, port, log level."""
        db.subscribeToSchema(engine_schema)
        with db.transaction():
            c = engine_schema.GitWatcherConfig.lookupAny(service=service_object)
            if not c:
                c = engine_schema.GitWatcherConfig(service=service_object)
            c.hostname = hostname
            c.port = port
            c.log_level = logging.getLevelName(level_name)
