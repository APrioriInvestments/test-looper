import logging

import object_database.web.cells as cells
from object_database import Index, Indexed

from .schema_declarations import repo_schema, test_schema, ui_schema
from ..utils import H1_FONTSIZE, TL_SERVICE_NAME, add_menu_bar, get_tl_link, setup_logger

logger = setup_logger(__name__, level=logging.INFO)


@ui_schema.define
class TestSuitesView:
    """Displays the test suite names and their associated tests for a given commit."""

    commit = Indexed(repo_schema.Commit)
    branch = Indexed(repo_schema.Branch)
    commit_and_branch = Index("commit", "branch")

    def display_cell(self):
        cells.ensureSubscribedSchema(test_schema)
        layout = cells.Padding(bottom=20) * cells.Text(
            "Test Suites for commit " + self.commit.hash, fontSize=H1_FONTSIZE
        )
        commit_test_definition = test_schema.CommitTestDefinition.lookupUnique(
            commit=self.commit
        )
        for test_suite_name, test_suite in commit_test_definition.test_suites.items():
            layout += cells.Text(test_suite_name, fontSize=H1_FONTSIZE)
            for test in test_suite.tests.keys():
                layout += cells.Text(test)

        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.commit.repo.name: get_tl_link(self.commit.repo),
            },
        )


@ui_schema.define
class BranchView:
    commit = Indexed(repo_schema.Commit)
    branch = Indexed(repo_schema.Branch)
    commit_and_branch = Index("commit", "branch")

    def display_cell(self):
        def rowFun():
            depth = 10

            commits = [self.commit]
            for ix in range(depth):
                commit = commits[-1]
                parents = repo_schema.CommitParent.lookupAll(child=commit)

                if len(parents) == 0:
                    break

                elif len(parents) > 1:
                    logger.error(
                        f"Commit {self.commit.hash} has {len(parents)} parents, "
                        "but only linear history with unique parent is supported."
                    )
                    break
                else:
                    assert len(parents) == 1
                    commits.append(parents[0].parent)

            return commits

        def rendererFun(commit, field):
            if field == "Hash":
                return cells.Clickable(commit.hash, get_tl_link(commit))
            elif field == "Autotesting":
                if (
                    cdt := test_schema.CommitDesiredTesting.lookupUnique(commit=commit)
                ) is None:
                    return "False"
                else:
                    return cdt.desired_testing.runs_desired > 0
            elif field == "Results Summary":
                results = test_schema.TestResults.lookupAll(commit=commit)
                completed = 0
                failed = 0
                for result in results:
                    if result.runs_completed:
                        completed += 1
                    if result.runs_failed:
                        failed += 1
                return f"{failed} / {completed} failed, {len(results)} available"
            elif field == "Commit Summary":
                return commit.commit_text
            elif field == "Author":
                return commit.author
            elif field == "Clear":
                return cells.Button("CLEAR", commit.clear_test_results)
            else:
                return f"Unexpected Field {field}"

        # common layout, should eventually be refactored out.
        def branch_view_on_click():
            if not (
                bv := ui_schema.BranchView.lookupUnique(
                    commit_and_branch=(self.branch.top_commit, self.branch)
                )
            ):
                bv = ui_schema.BranchView(commit=self.branch.top_commit, branch=self.branch)
            return get_tl_link(bv)

        repo = self.branch.repo
        layout = cells.Padding(bottom=20) * cells.Text(
            "Branch: " + self.branch.name, fontSize=H1_FONTSIZE
        )
        layout += cells.Button("View test matrix", get_tl_link(self.branch))
        layout += cells.Table(
            colFun=lambda: [
                "Hash",
                "Autotesting",
                "Results Summary",
                "Commit Summary",
                "Author",
                "Clear",
            ],
            rowFun=rowFun,
            headerFun=lambda x: x,
            rendererFun=rendererFun,
        )
        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                repo.name: get_tl_link(repo),
                self.branch.name: branch_view_on_click,
            },
        )
