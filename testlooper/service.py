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
from .utils import get_tl_link

logger = logging.getLogger(__name__)


class TestlooperService(ServiceBase):
    def initialize(self):
        # make sure we're subscribed to all objects in our schema.
        self.db.subscribeToSchema(repo_schema)

    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        print("displaying TL")
        cells.ensureSubscribedSchema(repo_schema)
        cells.ensureSubscribedSchema(ui_schema)
        m = f"serviceDisplay for {service_object}: instance {instance}, objType {objType}"
        logger.debug(m)
        if instance is not None:
            if hasattr(instance, "display_cell"):
                return cells.Card(cells.Subscribed(instance.display_cell))
            else:
                return cells.Card(cells.Subscribed(lambda: str(instance)))

        else:
            return Homepage.display_cell(service_object)


class Homepage:
    @classmethod
    def display_cell(cls, service_object):
        def rowFun():
            repo_rows = []
            repos = repo_schema.Repo.lookupAll()
            for repo in repos:
                if repo.primary_branch is None:
                    branch_cell = cells.Text("")
                    commit_cell = cells.Text("")
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
                        return get_tl_link(branch_view)

                    branch_cell = cells.Clickable(branch_name, on_click)
                    commit_cell = cells.Clickable(
                        branch.top_commit.hash, get_tl_link(branch.top_commit)
                    )

                repo_row = ConstDict(str, object)(
                    {
                        "Name": cells.Clickable(repo.name, get_tl_link(repo)),
                        "Primary Branch": branch_cell,
                        "Latest Commit": commit_cell,
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
        # reload_button = cells.Button("Reload", reload)
        layout = cells.HorizontalSequence(
            [cells.Button("TL", f"{service_object.name}")], margin=10
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

        layout += cells.Text("Repos")
        layout += cells.Card(repo_table)
        return layout
