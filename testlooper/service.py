"""service.py

This is the main entrypoint for testlooper. serviceDisplay is called
when the appropriate URL is used, with instance corresponding to
an object in the TL schema (e.g. Repo, Commit, Branch). We hit the
objects display method if it exists, otherwise we just return a string.

"""

import logging

import object_database.web.cells as cells
from object_database import ServiceBase

from .repo_schema import Repo, repo_schema

logger = logging.getLogger(__name__)


class TestlooperService(ServiceBase):
    def initialize(self):
        # make sure we're subscribed to all objects in our schema.
        self.db.subscribeToSchema(repo_schema)

    # def doWork(self, shouldStop):
    #     # this is the main entrypoint for the service - it gets to do work here.
    #     while not shouldStop.is_set():
    #         # wake up every 100ms and look at the objects in the ODB.
    #         time.sleep(.1)

    @staticmethod
    def serviceDisplay(serviceObject, instance=None, objType=None, queryArgs=None):
        print("displaying TL")
        cells.ensureSubscribedSchema(repo_schema)
        m = f"serviceDisplay for {serviceObject}: instance {instance}, objType {objType}"
        logger.debug(m)
        if instance is not None:
            if hasattr(instance, "display"):
                return cells.Card(cells.Subscribed(instance.display))
            else:
                return cells.Card(cells.Subscribed(lambda: str(instance)))

        else:
            return Homepage.display(serviceObject)


def reload():
    import os

    os._exit(0)


class Homepage:
    @classmethod
    def display(cls, serviceObject):
        print("displaying")
        repos = Repo.lookupAll()
        # buttons = []
        repo_rows = []
        for repo in repos:
            type_name = f"{repo_schema.name}.{type(repo).__name__}"
            link = f"{serviceObject.name}/{type_name}/{repo._identity}"
            # buttons.append(cells.Clickable(repo.name, link))
            repo_row = {
                "Name": cells.Clickable(repo.name, link),
                "Primary Branch": "dev",
                "Latest Commit": "bla",
                "Latest Test Run": "bla",
                "Primary Branch Status": "Passing",
                "Test Definitions": "bla",
                "Test Plan Generator": "bla",
                "Test Suites": "bla",
            }
            repo_rows.append(repo_row)

        # TODO use a headerbar
        reload_button = cells.Button("Reload", reload)
        layout = cells.HorizontalSequence(
            [reload_button, cells.Button("TL", f"{serviceObject.name}")], margin=10
        )

        repo_table = cells.Table.from_rows(repo_rows)
        layout += cells.Card(repo_table, header="Repos")
        return layout
