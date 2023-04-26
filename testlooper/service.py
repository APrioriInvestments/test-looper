"""service.py

This is the main entrypoint for testlooper. serviceDisplay is called
when the appropriate URL is used, with instance corresponding to
an object in the TL schema (e.g. Repo, Commit, Branch). We hit the
objects display method if it exists, otherwise we just return a string.

"""

import logging
import object_database.web.cells as cells
from object_database import ServiceBase
from typed_python import ConstDict

from .schemas import repo_schema, ui_schema

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
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        print("displaying TL")
        cells.ensureSubscribedSchema(repo_schema)
        cells.ensureSubscribedSchema(ui_schema)
        m = f"serviceDisplay for {service_object}: instance {instance}, objType {objType}"
        logger.debug(m)
        if instance is not None:
            if hasattr(instance, "display"):
                return cells.Card(cells.Subscribed(instance.display))
            else:
                return cells.Card(cells.Subscribed(lambda: str(instance)))

        else:
            return Homepage.display(service_object)


def reload():
    import os

    os._exit(0)


def get_link(service_object, instance):
    type_name = f"{instance.__schema__.name}.{type(instance).__name__}"
    return f"{service_object.name}/{type_name}/{instance._identity}"


class Homepage:
    @classmethod
    def display(cls, service_object):
        def rowFun():
            repo_rows = []
            repos = repo_schema.Repo.lookupAll()
            for repo in repos:
                if repo.primary_branch is None:
                    branch_cell = cells.Text("")
                else:
                    branch = repo.primary_branch
                    branch_name = branch.name

                    def get_or_create_branch_view():
                        commit = branch.top_commit

                        branch_view = ui_schema.BranchView.lookupUnique(
                            commit_and_branch=(commit, branch)
                        )
                        if branch_view is None:
                            branch_view = ui_schema.BranchView(branch=branch, commit=commit)

                        return branch_view

                    def on_click():
                        branch_view = get_or_create_branch_view()
                        return get_link(service_object, branch_view)

                    branch_cell = cells.Clickable(branch_name, on_click)

                repo_row = ConstDict(str, object)(
                    {
                        "Name": cells.Clickable(repo.name, get_link(service_object, repo)),
                        "Primary Branch": branch_cell,
                        "Latest Commit": "bla",
                        "Latest Test Run": "bla",
                        "Primary Branch Status": "Passing",
                        "Test Definitions": "bla",
                        "Test Plan Generator": "bla",
                        "Test Suites": "bla",
                    }
                )
                repo_rows.append(repo_row)
            return repo_rows

        def repoDataRenderer(data, field):
            return data[field]

        # TODO use a headerbar
        reload_button = cells.Button("Reload", reload)
        layout = cells.HorizontalSequence(
            [reload_button, cells.Button("TL", f"{service_object.name}")], margin=10
        )

        repo_table = cells.Table(
            colFun=lambda: [
                "Name",
                "Primary Branch",
                "Latest Commit",
                "Latest Test Run",
                "Primary Branch Status",
                "Test Definitions",
                "Test Plan Generator",
                "Test Suites",
            ],
            rowFun=rowFun,
            headerFun=lambda x: x,
            rendererFun=repoDataRenderer,
            maxRowsPerPage=100,
            sortColumn="Name",
        )

        layout += cells.Card(repo_table, header="Repos")
        return layout
