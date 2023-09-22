from dataclasses import dataclass
import logging
from collections import deque, defaultdict
from datetime import datetime
import functools
import object_database.web.cells as cells
import uuid
import yaml

from object_database import Index, Indexed
from typed_python import Alternative, ConstDict, Dict, OneOf
from typing import List

from .schema_declarations import repo_schema, ui_schema, test_schema, engine_schema
from ..utils import (
    H1_FONTSIZE,
    TL_SERVICE_NAME,
    add_menu_bar,
    get_tl_link,
    setup_logger,
    get_node_id,
)
from .test_schema import DesiredTesting, TestResults, TestFilter

logger = setup_logger(__name__, level=logging.INFO)


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
            "Repo:" + self.name, fontSize=H1_FONTSIZE
        )
        tl_config = self.primary_branch.top_commit.test_config
        test_plan = test_schema.TestPlan.lookupUnique(commit=self.primary_branch.top_commit)
        layout += cells.HorizontalSequence(
            [
                cells.Padding(padding=10) * b
                for b in [
                    cells.Button(
                        "View testlooper config", get_tl_link(tl_config) if tl_config else ""
                    ),
                    cells.Button(
                        "View test plan", get_tl_link(test_plan) if test_plan else ""
                    ),
                ]
            ]
        )

        # table with the branch information for this repo
        def row_fun():
            branch_rows = []
            branches = Branch.lookupAll(repo=self)
            for branch in branches:
                # don't generate the object unless user clicks on the link.
                def branch_view_on_click(branch):
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
                branch_test_status = "Passing" if commit_test_results else "Not Run"
                most_recent_timestamp = 0
                for test in commit_test_results:
                    most_recent_outcome = (
                        test.results[-1].outcome if test.results else "Not Run"
                    )
                    timestamp = test.results[-1].start_time if test.results else 0
                    if timestamp > most_recent_timestamp:
                        most_recent_timestamp = timestamp
                    if most_recent_outcome == "failed":
                        branch_test_status = "Failing"
                    elif most_recent_outcome == "error":
                        branch_test_status = "Error"
                    elif test.runs_pending:
                        branch_test_status = "Pending"

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
                            cells.Clickable(
                                branch.name,
                                functools.partial(branch_view_on_click, branch=branch),
                            )
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

    config_str = Indexed(str)
    repo = Indexed(Repo)
    # below fields all start as None until set.
    # needs_docker_build = OneOf(None, bool)
    image_name = OneOf(None, str)
    version = OneOf(None, str)
    name = OneOf(None, str)
    os = OneOf(None, str)
    variables = OneOf(None, Dict(str, str))
    image = OneOf(None, Dict(str, Dict(str, OneOf(str, bool))))
    command = OneOf(None, str)

    def display_cell(self) -> cells.Cell:
        """Simply display the yaml text."""

        layout = cells.Padding(bottom=20) * cells.Text("Test Config", fontSize=H1_FONTSIZE)
        layout += cells.Scrollable(cells.Code(self.config_str))
        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.repo.name: get_tl_link(self.repo),
            },
        )

    def parse_config(self):
        """Parse and validate the yaml, populate schema fields."""
        test_config = yaml.safe_load(self.config_str)

        # see docs/Repo_Configuration_Spec.md
        required_keys = ["version", "name", "image", "command"]
        for key in required_keys:
            if key not in test_config:
                raise ValueError(f"Missing required key {key} in config.yaml")
        for key in ["version", "name", "os", "variables", "image", "command"]:
            try:
                if type(test_config[key]) is not dict:
                    val = str(test_config[key])
                else:
                    val = test_config[key]
                setattr(self, key, val)

            except KeyError:
                continue

        if self.image.get("aws-ami"):
            raise NotImplementedError("AWS AMI images not yet supported")


@repo_schema.define
class Commit:
    hash = Indexed(str)
    repo = Indexed(Repo)
    repo_and_hash = Index("repo", "hash")

    commit_text = str
    author = str
    # this is set by GenerateTestConfigTask
    test_config = OneOf(None, repo_schema.TestConfig)

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
        logger.info(f"Clearing Test Results for commit {self.hash}")
        for result in test_schema.TestResults.lookupAll(commit=self):
            result.clear_results()

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
        commit_desired_testing = test_schema.CommitDesiredTesting.lookupUnique(commit=self)
        if commit_desired_testing is not None:
            desired_testing = commit_desired_testing.desired_testing
            new_desired_testing = desired_testing.replacing(
                runs_desired=desired_testing.runs_desired + 1,
                filter=TestFilter(labels="Any", path_prefixes="Any", suites="Any", regex=None),
            )
            commit_desired_testing.update_desired_testing(new_desired_testing)

    def rerun_failed_tests(self):
        """Suboptimally, look for failing tests and submit Tasks directly.

        This involves looping over all tests to find the right suite. We have to do this
        because DesiredTesting doesn't quite support this.
        """
        test_results = test_schema.TestResults.lookupAll(commit=self)
        test_suites = defaultdict(list)
        for test_result in test_results:
            if test_result.runs_failed:
                test_result.runs_desired += 1
                test_suites[test_result.suite].append(get_node_id(test_result.test))

        for suite, node_ids in test_suites.items():
            engine_schema.TestSuiteRunTask.create(
                uuid=str(uuid.uuid4()), commit=self, suite=suite, test_node_ids=node_ids
            )

        logger.info(f"Rerunning failed tests for commit {self.hash}")

    def display_cell(self) -> cells.Cell:
        """Called by serviceDisplay, returns the Cell for the page representing this commit."""
        layout = cells.Text("Commit: " + self.hash, fontSize=H1_FONTSIZE)
        layout += cells.Padding(bottom=20) * cells.Text(self.commit_text)

        ctd = test_schema.CommitTestDefinition.lookupUnique(commit=self)

        def renderer_fun(row, field):
            suite, test = row
            result = test_schema.TestResults.lookupUnique(test_and_commit=(test, self))
            if field == "Environment":
                return suite.environment.name
            elif field == "Suite":
                return suite.name
            elif field == "Test Name":
                return cells.Clickable(test.name, get_tl_link(test))
            elif field == "Status":
                text = ""
                if result.runs_pending:
                    text = "PENDING"
                else:
                    if result.runs_errored:
                        text = "ERROR"
                    elif result.runs_failed:
                        text = "FAILED"
                    else:
                        text = "PASSED"
                return cells.Clickable(text, get_tl_link(result))
            elif field == "Failure Rate":
                return round(result.fail_rate(), 2)
            elif field == "Failure Count":
                return result.runs_failed
            elif field == "Runs Completed":
                return result.runs_completed
            elif field == "Duration":
                return (
                    str(round(result.results[-1].duration_ms, 2)) + " ms"
                    if result.results
                    else "N/A"
                )
            elif field == "Currently Running":
                return "True" if result.runs_pending else "False"

        table = cells.Table(
            colFun=lambda: [
                "Environment",
                "Suite",
                "Test Name",
                "Status",
                "Failure Rate",
                "Failure Count",
                "Runs Completed",
                "Duration",
                "Currently Running",
            ],
            rowFun=lambda: [
                (suite, test)
                for suite in ctd.test_suites.values()
                for test in suite.tests.values()
            ],
            headerFun=lambda x: x,
            rendererFun=renderer_fun,
        )

        def get_or_create_testing_config():
            if (
                commit_desired_testing := test_schema.CommitDesiredTesting.lookupUnique(
                    commit=self
                )
            ) is None:
                commit_desired_testing = test_schema.CommitDesiredTesting(commit=self)
            return commit_desired_testing

        def on_config_click():
            config = get_or_create_testing_config()
            return get_tl_link(config)

        layout += cells.HorizontalSequence(
            [
                cells.Sequence(
                    [
                        cells.Button("Rerun all tests", self.rerun_all_tests),
                        cells.Button("Rerun failed tests", self.rerun_failed_tests),
                        cells.Button("Configure rerun", on_config_click),
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


@dataclass(eq=True, frozen=True)
class TestRow:
    test_name: str
    suite_name: str
    env_name: str
    # test: test_schema.Test
    test_results: ConstDict(str, TestResults)  # commit hash to result


@repo_schema.define
class Branch:
    repo = Indexed(Repo)
    name = str
    repo_and_name = Index("repo", "name")
    top_commit = Indexed(Commit)

    def display_cell(self) -> cells.Cell:
        """
        Shows a table in which the commits are columns, and the test names are rows.

        Slots track the leftmost commit, though this is never updated, and we show 10
        commits total.
        """

        leftmost_commit = cells.Slot(self.top_commit)
        failed_tests_only = cells.Slot(False)
        all_failed_tests_only = cells.Slot(False)
        layout = cells.Padding(bottom=20) * cells.Text(
            "Branch: " + self.name, fontSize=H1_FONTSIZE
        )

        def branch_view_on_click():
            if not (
                bv := ui_schema.BranchView.lookupUnique(
                    commit_and_branch=(self.top_commit, self)
                )
            ):
                bv = ui_schema.BranchView(commit=self.top_commit, branch=self)
            return get_tl_link(bv)

        layout += cells.Padding(bottom=20) * cells.Button(
            "View linear summary", branch_view_on_click
        )

        layout += cells.Button("Show most recent failed tests", failed_tests_only.toggle)
        layout += cells.Button("Show all failed tests", all_failed_tests_only.toggle)

        def get_most_recent_commits(commit: Commit, N: int) -> List[Commit]:
            """Return the commit objects to use as columns in the table.

            Requires a linear history."""
            commits = [commit]
            current_commit = commit
            for _ in range(N - 1):
                parents = current_commit.parents
                if len(parents) == 0:
                    break
                if len(parents) != 1:
                    raise ValueError("Commit history is not linear")
                current_commit = parents[0]
                commits.append(current_commit)
            return commits

        def row_fun():
            """Get all Tests for the last 10 commits

            TODO: make Slot-based, don't hardcode the number, likely to be unperformant"""
            recent_tests = defaultdict(dict)

            for commit in get_most_recent_commits(leftmost_commit.get(), N=10):
                ctd = test_schema.CommitTestDefinition.lookupUnique(commit=commit)
                if ctd is None:
                    continue
                for suite_name, suite in ctd.test_suites.items():
                    for test in suite.tests.values():
                        recent_tests[(suite_name, suite.environment.name, test.name)][
                            commit.hash
                        ] = test_schema.TestResults.lookupUnique(
                            test_and_commit=(test, commit)
                        )

            # convert to TestRows, filter.
            test_rows = []
            for (suite, env, test_name), commit_to_result_dict in recent_tests.items():
                if failed_tests_only.get():
                    # then filter to only the test_rows with failed in the leftmost_commit.
                    if (
                        x := commit_to_result_dict.get(leftmost_commit.get().hash, None)
                    ) is not None and x.runs_failed:
                        test_rows.append(
                            TestRow(
                                test_name=test_name,
                                suite_name=suite,
                                env_name=env,
                                test_results=ConstDict(str, TestResults)(
                                    commit_to_result_dict
                                ),
                            )
                        )

                elif all_failed_tests_only.get():
                    # then if there is any failed test in the commit_to_result_dict, add it.
                    for result in commit_to_result_dict.values():
                        if result.runs_failed:
                            test_rows.append(
                                TestRow(
                                    test_name=test_name,
                                    suite_name=suite,
                                    env_name=env,
                                    test_results=ConstDict(str, TestResults)(
                                        commit_to_result_dict
                                    ),
                                )
                            )
                            break
                else:
                    try:
                        test_rows.append(
                            TestRow(
                                test_name=test_name,
                                suite_name=suite,
                                env_name=env,
                                test_results=ConstDict(str, TestResults)(
                                    commit_to_result_dict
                                ),
                            )
                        )
                    except TypeError:
                        # occurs if the test matrix is partially initialised
                        continue

            return test_rows

        def renderer_fun(row: TestRow, field_name: str) -> cells.Cell:
            if field_name == "Test Name":
                # For now, assume unique test names.
                return cells.Clickable(
                    row.test_name,
                    get_tl_link(test_schema.Test.lookupUnique(name=row.test_name)),
                )
            elif field_name == "Suite Name":
                return row.suite_name
            elif field_name == "Environment Name":
                return row.env_name
            else:
                # field name is a commit hash.
                result = row.test_results.get(field_name)
                if result is None:
                    return "NA"
                else:
                    if result.runs_errored > 0:
                        result_text = cells.Text("ERROR", text_color="red")
                    elif result.runs_failed > 0:
                        result_text = cells.Text("FAILED", text_color="red")
                    elif result.runs_pending > 0:
                        result_text = cells.Text("PENDING", text_color="orange")
                    else:
                        result_text = "PASSED"
                    return cells.Clickable(
                        result_text,
                        get_tl_link(result),
                    )

        headers = ["Test Name", "Suite Name", "Environment Name"]

        def get_clickable(x):
            if x in headers:
                return x
            else:
                return cells.Clickable(x, get_tl_link(repo_schema.Commit.lookupUnique(hash=x)))

        table = cells.Scrollable(
            cells.Table(
                colFun=lambda: headers
                + [x.hash for x in get_most_recent_commits(leftmost_commit.get(), N=10)],
                rowFun=row_fun,
                headerFun=lambda x: get_clickable(x),
                rendererFun=renderer_fun,
                sortColumn=0,
                maxRowsPerPage=250,
            )
        )
        layout += table

        return add_menu_bar(
            cells.HCenter(layout),
            {
                "TL": f"/services/{TL_SERVICE_NAME}",
                self.repo.name: get_tl_link(self.repo),
                self.name: get_tl_link(self),
            },
        )

    def set_desired_testing(self, desired_testing: DesiredTesting):
        _ = test_schema.BranchDesiredTesting(branch=self, desired_testing=desired_testing)
