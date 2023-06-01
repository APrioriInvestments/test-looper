from object_database import Reactor, ServiceBase

from testlooper.engine.local_engine_agent import LocalEngineAgent
from testlooper.schema.schema import engine_schema


class LocalEngineService(ServiceBase):
    def initialize(self):
        self.db.subscribeToSchema(engine_schema)

        with self.db.transaction():
            config = engine_schema.LocalEngineConfig.lookupUnique()

            if config is None:
                config = engine_schema.LocalEngineConfig(config="blank")

        self.agent = LocalEngineAgent(self.db, source_control_store=None, artifact_store=None)

        self.registerReactor(Reactor(self.db, self.agent.generate_test_plans))
