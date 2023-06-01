from object_database import ServiceBase, Schema, Reactor

from .local_engine_agent import LocalEngineAgent

local_engine_schema = Schema("local_engine_schema")


@local_engine_schema.define
class LocalEngineConfig:
    pass


class LocalEngineService(ServiceBase):
    def initialize(self):
        with self.db.view():
            config = local_engine_schema.LocalEngineConfig.lookupUnique()

            if config is None:
                config = local_engine_schema.LocalEngineConfig()

        self.agent = LocalEngineAgent(self.db)

        self.registerReactor(Reactor(self.db, self.agent.generate_test_plans))
