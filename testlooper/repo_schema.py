import logging

import object_database.web.cells as cells
from object_database import Index, Indexed
from typed_python import Alternative, ConstDict, OneOf

from .schema_declarations import repo_schema, ui_schema
from . import TL_SERVICE_NAME
from .utils import get_tl_link

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
        # common layout, should eventually be refactored out.
        layout = cells.HorizontalSequence(
            [
                cells.Button("TL", f"/services/{TL_SERVICE_NAME}"),
                cells.Button(self.name, get_tl_link(self)),
            ],
            margin=100,
        )
        layout += cells.Text("Repo: " + self.name, fontSize=20)
        layout += cells.HorizontalSequence(
            [
                cells.Button("View test_definitions file", "/td"),
                cells.Button("View test plan generator", "/tpg"),
                cells.Button("View test plan", "/tp"),
            ],
            margin=100,
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

                branch_row = ConstDict(str, object)(
                    {
                        "Branch Name": cells.Clickable(branch.name, branch_view_on_click),
                        "Last Run": "TODO",
                        "Status": "TODO",
                        "Autotesting": "Yes",
                        "Latest Commit": cells.Clickable(
                            branch.top_commit.hash, get_tl_link(branch.top_commit)
                        ),
                        "Rerun All Tests": cells.Button("", "/rerun_all_tests"),
                        "Rerun Most Recent Failed Tests": cells.Button(
                            "", "/rerun_failed_tests"
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
        return layout


@repo_schema.define
class Commit:
    hash = Indexed(str)
    repo = Indexed(Repo)
    repo_and_hash = Index("repo", "hash")

    commit_text = str
    author = str

    # allows us to ask which commits need us to parse their tests. One of our services
    # is a little state machine that will run through Commit objects that are not parsed
    test_plan_generated = Indexed(bool)

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

    def clear_test_results(self):
        # TODO
        logger.info(f"Clearing Test Results for commit {self.hash}")
        pass

    def get_closest_branch(self):
        """Returns the first branch reached by doing a breadth-first-serach on children."""
        # TODO
        pass

    def display_cell(self) -> cells.Cell:
        """Called by serviceDisplay, returns the Cell for the page representing this commit."""
        # common layout for header bar, should eventually be refactored out.
        layout = cells.HorizontalSequence(
            [
                cells.Button("TL", f"/services/{TL_SERVICE_NAME}"),
                cells.Button(self.repo.name, get_tl_link(self.repo)),
                cells.Button(self.hash, get_tl_link(self)),
            ],
            margin=100,
        )
        layout += cells.Text("Commit: " + self.hash, fontSize=20)
        layout += cells.Text(self.commit_text)

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
                        cells.Button("Rerun all tests", "/rerun_all_tests"),
                        cells.Button("Rerun failed tests", "/rerun_failed_tests"),
                        cells.Button("Configure rerun", "/configure_rerun"),
                    ]
                ),
                table,
            ]
        )
        return layout


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
    top_commit = Commit
