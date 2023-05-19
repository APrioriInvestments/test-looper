import logging
from collections import deque
from datetime import datetime
import object_database.web.cells as cells
from object_database import Index, Indexed
from typed_python import Alternative, ConstDict, OneOf

from .schema_declarations import repo_schema, ui_schema, test_schema
from .utils import HEADER_FONTSIZE, TL_SERVICE_NAME, add_menu_bar, get_tl_link
from .test_schema import DesiredTesting

logger = logging.getLogger(__name__)


# describe generic services, which can provide lots of different repos
GitService = Alternative(
    "GitService",
    Github=dict(
        oauth_key=str,
        oauth_secret=str,
        webhook_secret=str,
        owner=str,  # owner we use to specify which projects to look at
        access_token=str,
        auth_disabled=bool,
        github_url=str,  # usually https://github.com
        github_login_url=str,  # usually https://github.com
        github_api_url=str,  # usually https://github.com/api/v3
        github_clone_url=str,  # usually git@github.com
    ),
    Gitlab=dict(
        oauth_key=str,
        oauth_secret=str,
        webhook_secret=str,
        group=str,  # group we use to specify which projects to show
        private_token=str,
        auth_disabled=bool,
        gitlab_url=str,  # usually https://gitlab.mycompany.com
        gitlab_login_url=str,  # usually https://gitlab.mycompany.com
        gitlab_api_url=str,  # usually https://gitlab.mycompany.com/api/v3
        gitlab_clone_url=str,  # usually git@gitlab.mycompany.com
    ),
)


# describe how to get access to a specific repo
RepoConfig = Alternative(
    "RepoConfig",
    Ssh=dict(url=str, privateKey=bytes),
    Http=dict(url=str),
    Local=dict(path=str),
    FromService=dict(repo_name=str, service=GitService),
)


@repo_schema.define
class Repo:
    name = Indexed(str)
    config = RepoConfig
    primary_branch = OneOf(None, repo_schema.Branch)

    def display_cell(self) -> cells.Cell:
        """Returns the Cells object for the repo page."""
        layout = cells.Padding(bottom=20) * cells.Text(
            "Repo:" + self.name, fontSize=HEADER_FONTSIZE
        )
        tl_config = self.primary_branch.top_commit.test_config
        test_plan = test_schema.TestPlan.lookupUnique(commit=self.primary_branch.top_commit)
        layout += cells.HorizontalSequence(
            [
                cells.Padding(padding=10) * b
                for b in [
                    cells.Button("View testlooper config", get_tl_link(tl_config)),
                    cells.Button("View test plan", get_tl_link(test_plan)),
                ]
            ]
        )

        # table with the branch information for this repo
        def row_fun():
            branch_rows = []
            branches = Branch.lookupAll(repo=self)
            for branch in branches:
                # don't generate the object unless user clicks on the link.
                def branch_view_on_click():
                    if not (
                        bv := ui_schema.BranchView.lookupUnique(
                            commit_and_branch=(branch.top_commit, branch)
                        )
                    ):
                        bv = ui_schema.BranchView(commit=branch.top_commit, branch=branch)
                    return get_tl_link(bv)

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
                    formatted_time = datetime.utcfromtimestamp(most_recent_timestamp).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    )
                else:
                    formatted_time = ""

                most_recent_test_run_cell = cells.HCenter(cells.Text(formatted_time))
                branch_test_status_cell = cells.HCenter(cells.Text(branch_test_status))
                # autotesting is true while it lives in the hearts of men
                # (or while we have a branchdesiredtesting object)
                # we assume that if we have a BranchDesiredTesting object,
                # if has runs_desired >= 1
                autotesting = (
                    "Yes"
                    if test_schema.BranchDesiredTesting.lookupUnique(branch=branch) is not None
                    else "No"
                )
                branch_row = ConstDict(str, object)(
                    {
                        "Branch Name": cells.HCenter(
                            cells.Clickable(branch.name, branch_view_on_click)
                        ),
                        "Last Run": most_recent_test_run_cell,
                        "Status": branch_test_status_cell,
                        "Autotesting": cells.HCenter(cells.Text(autotesting)),
                        "Latest Commit": cells.HCenter(
                            cells.Clickable(
                                branch.top_commit.hash, get_tl_link(branch.top_commit)
                            )
                        ),
                        "Rerun All Tests": cells.HCenter(
                            cells.Button("", branch.top_commit.rerun_all_tests)
                        ),
                        "Rerun Most Recent Failed Tests": cells.HCenter(
                            cells.Button("", branch.top_commit.rerun_failed_tests)
                        ),
                    }
                )
                branch_rows.append(branch_row)
            return branch_rows

        def renderer_fun(data, field):
            return data[field]

        repo_table = cells.Table(
            colFun=lambda: [
                "Branch Name",
                "Last Run",
                "Status",
                "Autotesting",
                "Latest Commit",
                "Rerun All Tests",
                "Rerun Most Recent Failed Tests",
            ],
            rowFun=row_fun,
            headerFun=lambda x: x,
            rendererFun=renderer_fun,
            maxRowsPerPage=100,
            sortColumn="Last Run",
        )
        layout += cells.Card(repo_table)
        return add_menu_bar(
            cells.HCenter(layout),
            {"TL": f"/services/{TL_SERVICE_NAME}", self.name: get_tl_link(self)},
        )


@repo_schema.define
class TestConfig:
    """Contains the text of the .testlooper/config.yaml for one or more commits."""

    config = Indexed(str)
    repo = Indexed(Repo)

    def display_cell(self) -> cells.Cell:
        """Simply display the yaml text."""

        layout = cells.Padding(bottom=20) * cells.Text("Test Config", fontSize=HEADER_FONTSIZE)
        layout += cells.Scrollable(cells.Code(self.config))
        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.repo.name: get_tl_link(self.repo),
            },
        )


@repo_schema.define
class Commit:
    hash = Indexed(str)
    repo = Indexed(Repo)
    repo_and_hash = Index("repo", "hash")

    commit_text = str
    author = str

    test_config = repo_schema.TestConfig

    @property
    def parents(self):
        """Return a list of parent commits"""
        return [c.parent for c in CommitParent.lookupAll(child=self)]

    @property
    def children(self):
        return [c.child for c in CommitParent.lookupAll(parent=self)]

    def set_parents(self, parents):
        """Utility function to manage CommitParent objects"""
        curParents = self.parents
        for p in curParents:
            if p not in parents:
                CommitParent.lookupOne(parentAndChild=(p, self)).delete()

        for p in parents:
            if p not in curParents:
                CommitParent(parent=p, child=self)

    def get_test_suite(self, name):
        """Find the TestSuite that corresponds to a commit."""
        test_definition = test_schema.CommitTestDefinition.lookupUnique(commit=self)
        if test_definition is None:
            return None

        return test_definition.test_suites.get(name, None)

    def clear_test_results(self):
        # TODO
        logger.info(f"Clearing Test Results for commit {self.hash}")
        pass

    def get_closest_branch(self, max_depth=100):
        """Returns the branch with top_commit closest to this commit (or None if not found)"""
        queue = deque([(self, 0)])  # queue for BFS, with (commit, depth) pairs
        visited = set()  # set to store visited commits

        while queue:
            current_commit, depth = queue.popleft()
            if depth > max_depth:
                return None  # no branch was found in sufficient depth

            if current_commit in visited:
                continue

            visited.add(current_commit)

            # Check if the current commit is in any branch
            branches = repo_schema.Branch.lookupAll(top_commit=current_commit)
            if branches:
                return branches[0]  # return the first branch found

            # Add children to the queue
            children = repo_schema.CommitParent.lookupAll(parent=current_commit)
            for child in children:
                queue.append((child.child, depth + 1))

        return None  # no branch was found for the given commit

    def rerun_all_tests(self):
        # TODO
        logger.info(f"Rerunning all tests for commit {self.hash}")

    def rerun_failed_tests(self):
        # TODO
        logger.info(f"Rerunning failed tests for commit {self.hash}")

    def display_cell(self) -> cells.Cell:
        """Called by serviceDisplay, returns the Cell for the page representing this commit."""
        layout = cells.Text("Commit: " + self.hash, fontSize=HEADER_FONTSIZE)
        layout += cells.Padding(bottom=20) * cells.Text(self.commit_text)

        # table with test run info for this commit
        def row_fun():
            return [
                ConstDict(str, str)(
                    {
                        "Environment": "TODO",
                        "Suite": "TODO",
                        "Test Name": "TODO",
                        "Status": "TODO",
                        "Failure Rate": "TODO",
                        "Failure Count": "TODO",
                        "Duration": "TODO",
                        "Currently Running": "TODO",
                    }
                )
            ]

        def renderer_fun(data, field):
            return data[field]

        table = cells.Table(
            colFun=lambda: [
                "Environment",
                "Suite",
                "Test Name",
                "Status",
                "Failure Rate",
                "Failure Count",
                "Duration",
                "Currently Running",
            ],
            rowFun=row_fun,
            headerFun=lambda x: x,
            rendererFun=renderer_fun,
        )

        layout += cells.HorizontalSequence(
            [
                cells.Sequence(
                    [
                        cells.Button("See diff", "/diff"),
                        cells.Button("Rerun all tests", self.rerun_all_tests),
                        cells.Button("Rerun failed tests", self.rerun_failed_tests),
                        cells.Button("Configure rerun", "/configure_rerun"),
                    ]
                ),
                table,
            ]
        )
        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.repo.name: get_tl_link(self.repo),
                self.hash: get_tl_link(self),
            },
        )


@repo_schema.define
class CommitParent:
    """Model the parent-child relationshp between two commits"""

    parent = Indexed(Commit)
    child = Indexed(Commit)

    parent_and_child = Index("parent", "child")


@repo_schema.define
class Branch:
    repo = Indexed(Repo)
    name = str

    repo_and_name = Index("repo", "name")
    top_commit = Indexed(Commit)

    def set_desired_testing(self, desired_testing: DesiredTesting):
        _ = test_schema.BranchDesiredTesting(branch=self, desired_testing=desired_testing)
