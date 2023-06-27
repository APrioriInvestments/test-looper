import logging
from object_database import Reactor, ServiceBase
import object_database.web.cells as cells
from testlooper.engine.local_engine_agent import LocalEngineAgent
from testlooper.schema.schema import engine_schema
from testlooper.vcs import Git
from testlooper.utils import setup_logger


logger = setup_logger(__name__, level=logging.INFO)


class LocalEngineService(ServiceBase):
    """Grabs the config and then spins up a Reactor to look for TestPlanGenerationTasks.

    If no such config exists, it will throw.

    Name is, for now, a misnomer.
    """

    def initialize(self):
        logger.info("Initializing LocalEngineService")
        self.db.subscribeToSchema(engine_schema)

        with self.db.transaction():
            config = engine_schema.LocalEngineConfig.lookupUnique()

            if config is None:
                raise RuntimeError("No LocalEngineConfig found in the database.")

            repo_path = config.path_to_git_repo

        git_repo = Git.get_instance(repo_path)
        self.agent = LocalEngineAgent(
            self.db, source_control_store=git_repo, artifact_store=None
        )

        self.registerReactor(Reactor(self.db, self.agent.generate_test_plans))
        self.registerReactor(Reactor(self.db, self.agent.generate_test_suites))
        self.registerReactor(Reactor(self.db, self.agent.run_tests))
        self.registerReactor(Reactor(self.db, self.agent.generate_commit_test_definitions))

    # todo - a serviceDisplay method showing what the engine is up to,
    # whether the reactor is running, etc
    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        return cells.Card(cells.Text(str(service_object)))
