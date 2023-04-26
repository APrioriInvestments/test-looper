import logging

import object_database.web.cells as cells
from object_database import Index, Indexed

from . import TL_SERVICE_NAME
from .schema_declarations import repo_schema, ui_schema
from .utils import get_tl_link

logger = logging.getLogger(__name__)


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
            elif field == "Testing":
                return "False"  # TODO
            elif field == "Results Summary":
                return None  # TODO
            elif field == "Commit Summary":
                return commit.commit_text
            elif field == "Author":
                return commit.author
            elif field == "Clear":
                return cells.Button("CLEAR", commit.clear_test_results)  # TODO
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
        layout = cells.HorizontalSequence(
            [
                cells.Button("TL", f"/services/{TL_SERVICE_NAME}"),
                cells.Button(repo.name, get_tl_link(repo)),
                cells.Button(self.branch.name, branch_view_on_click),
            ],
            margin=100,
        )
        layout += cells.Text("Branch: " + self.branch.name, fontSize=20)
        layout += cells.Table(
            colFun=lambda: [
                "Hash",
                "Testing",
                "Results Summary",
                "Commit Summary",
                "Author",
                "Clear",
            ],
            rowFun=rowFun,
            headerFun=lambda x: x,
            rendererFun=rendererFun,
        )
        return layout
