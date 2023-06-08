"""service.py

This is the main entrypoint for testlooper. serviceDisplay is called
when the appropriate URL is used, with instance corresponding to
an object in the TL schema (e.g. Repo, Commit, Branch). We hit the
objects display method if it exists, otherwise we just return a string.

"""
from datetime import datetime
import logging

import object_database.web.cells as cells
from object_database import ServiceBase
from typed_python import ConstDict

from .schema.schema import engine_schema, repo_schema, test_schema, ui_schema
from .utils import H1_FONTSIZE, add_menu_bar, get_tl_link

logger = logging.getLogger(__name__)


class TestlooperService(ServiceBase):
    def initialize(self):
        # make sure we're subscribed to all objects in our schema.
        self.db.subscribeToSchema(repo_schema, engine_schema, test_schema, ui_schema)

    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        cells.ensureSubscribedSchema(repo_schema)
        cells.ensureSubscribedSchema(ui_schema)
        cells.ensureSubscribedSchema(test_schema)
        cells.ensureSubscribedSchema(engine_schema)
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
                    most_recent_test_run_cell = cells.Text("")
                    branch_test_status_cell = cells.Text("")
                    config_cell = cells.Text("")
                    test_plan_cell = cells.Text("")
                    suites_cell = cells.Button("", "")
                else:
                    branch = repo.primary_branch
                    branch_name = branch.name

                    def get_or_create_branch_view():
                        commit = branch.top_commit
                        if (
                            branch_view := ui_schema.BranchView.lookupUnique(
                                commit_and_branch=(commit, branch)
                            )
                        ) is None:
                            branch_view = ui_schema.BranchView(branch=branch, commit=commit)
                        return branch_view

                    def get_or_create_suites_view():
                        commit = branch.top_commit
                        if (
                            suites_view := ui_schema.TestSuitesView.lookupUnique(
                                commit_and_branch=(commit, branch)
                            )
                        ) is None:
                            suites_view = ui_schema.TestSuitesView(
                                branch=branch, commit=commit
                            )
                        return suites_view

                    def on_branch_click():
                        branch_view = get_or_create_branch_view()
                        return get_tl_link(branch_view)

                    def on_suites_click():
                        suites_view = get_or_create_suites_view()
                        return get_tl_link(suites_view)

                    branch_cell = cells.HCenter(cells.Clickable(branch_name, on_branch_click))

                    commit_cell = cells.HCenter(
                        cells.Clickable(branch.top_commit.hash, get_tl_link(branch.top_commit))
                    )

                    # 'Passing' if the most recent TestRunResult for the tests of the top
                    # commit are all passing, 'Failing' otherwise.
                    # NB: requires a full scan of the tests, could be optimized.
                    commit_test_results = test_schema.TestResults.lookupAll(
                        commit=branch.top_commit
                    )
                    branch_test_status = "Passing"
                    most_recent_timestamp = 0
                    for test in commit_test_results:
                        most_recent_outcome = (
                            test.results[-1].outcome if test.results else "not run"
                        )
                        timestamp = test.results[-1].start_time if test.results else 0
                        if timestamp > most_recent_timestamp:
                            most_recent_timestamp = timestamp
                        if most_recent_outcome == "failed":
                            branch_test_status = "Failing"

                    if most_recent_timestamp > 0:
                        formatted_time = datetime.utcfromtimestamp(
                            most_recent_timestamp
                        ).strftime("%Y-%m-%d %H:%M:%S UTC")
                    else:
                        formatted_time = ""

                    most_recent_test_run_cell = cells.HCenter(cells.Text(formatted_time))
                    branch_test_status_cell = cells.HCenter(cells.Text(branch_test_status))

                    config_cell = cells.HCenter(
                        cells.Button("", get_tl_link(branch.top_commit.test_config))
                    )

                    ctd = test_schema.CommitTestDefinition.lookupUnique(
                        commit=branch.top_commit
                    )
                    test_plan = ctd.test_plan if ctd is not None else None
                    test_plan_cell = cells.HCenter(
                        cells.Button(
                            "", get_tl_link(test_plan) if test_plan is not None else ""
                        )
                    )

                    suites_cell = cells.HCenter(cells.Button("", on_suites_click))

                repo_row = ConstDict(str, object)(
                    {
                        "Name": cells.HCenter(cells.Clickable(repo.name, get_tl_link(repo))),
                        "Primary Branch": branch_cell,
                        "Top Commit": commit_cell,
                        "Most Recent Test Run": most_recent_test_run_cell,
                        "Primary Branch Status": branch_test_status_cell,
                        "Testlooper Config": config_cell,
                        "Repo Test Plan": test_plan_cell,
                        "Test Suites": suites_cell,
                    }
                )
                repo_rows.append(repo_row)
            return repo_rows

        def repoDataRenderer(data, field):
            return data[field]

        repo_table = cells.Table(
            colFun=lambda: [
                "Name",
                "Primary Branch",
                "Top Commit",
                "Most Recent Test Run",
                "Primary Branch Status",
                "Testlooper Config",
                "Repo Test Plan",
                "Test Suites",
            ],
            rowFun=rowFun,
            headerFun=lambda x: x,
            rendererFun=repoDataRenderer,
            maxRowsPerPage=100,
            sortColumn="Name",
        )

        layout = cells.Padding(bottom=20) * cells.Text("Repos", fontSize=H1_FONTSIZE)
        layout += cells.Card(repo_table)

        machines_table = cells.Table(
            colFun=lambda: ["Machine ID", "Hardware", "OS", "Uptime", "Status", "Logs"],
            rowFun=lambda: [],
            headerFun=lambda x: x,
            rendererFun=lambda data, field: data[field],
            maxRowsPerPage=100,
            sortColumn="Machine ID",
        )

        layout += cells.Padding(top=50) * cells.Text(
            "Machines", fontSize=H1_FONTSIZE
        ) + cells.Card(machines_table)
        return add_menu_bar(cells.HCenter(layout), {"TL": service_object.name})
