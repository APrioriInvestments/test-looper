import logging

from object_database import Indexed, Index
import object_database.web.cells as cells

from .schema_declarations import ui_schema, repo_schema


logger = logging.getLogger(__name__)


@ui_schema.define
class BranchView:
    commit = Indexed(repo_schema.Commit)
    branch = Indexed(repo_schema.Branch)
    commit_and_branch = Index("commit", "branch")

    def display(self):
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
                return commit.hash
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

        table = cells.Table(
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
        return table
