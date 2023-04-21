"""service.py

This is the main entrypoint for testlooper. serviceDisplay is called
when the appropriate URL is used, with instance corresponding to
an object in the TL schema (e.g. Repo, Commit, Branch). We hit the
objects display method if it exists, otherwise we just return a string.

"""

import logging

import object_database.web.cells as cells
from object_database import ServiceBase

from .schema import Repo, test_looper_schema

logger = logging.getLogger(__name__)


class TestlooperService(ServiceBase):
    def initialize(self):
        # make sure we're subscribed to all objects in our schema.
        self.db.subscribeToSchema(test_looper_schema)

    # def doWork(self, shouldStop):
    #     # this is the main entrypoint for the service - it gets to do work here.
    #     while not shouldStop.is_set():
    #         # wake up every 100ms and look at the objects in the ODB.
    #         time.sleep(.1)

    @staticmethod
    def serviceDisplay(serviceObject, instance=None, objType=None, queryArgs=None):
        cells.ensureSubscribedSchema(test_looper_schema)
        m = f"serviceDisplay for {serviceObject}: instance {instance}, objType {objType}"
        logger.debug(m)
        if instance is not None:
            if hasattr(instance, "display"):
                return cells.Card(cells.Subscribed(instance.display))
            else:
                return cells.Card(cells.Subscribed(lambda: str(instance)))

        else:
            # TODO put this main page logic somewhere else.
            repos = Repo.lookupAll()
            buttons = []
            for repo in repos:
                type_name = f"{test_looper_schema.name}.{type(repo).__name__}"
                link = f"{serviceObject.name}/{type_name}/{repo._identity}"
                buttons.append(cells.Clickable(repo.name, link))

            reload_button = cells.Button("Reload", reload)
            return cells.Panel(
                reload_button
                + cells.Clickable("BACK", f"{serviceObject.name}")
                + cells.Sequence(buttons)
            )


def reload():
    import os

    os._exit(0)
