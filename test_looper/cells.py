import time
import subprocess

import object_database.web.cells as cells
from object_database.web.cells.webgl_plot import Color
from object_database import connect, ServiceBase
from object_database.web.cells.webgl_plot import Plot

from test_looper import test_looper_schema
from test_looper.test_schema import TestResults
from test_looper.repo_schema import Commit, Branch, Repository
from test_looper.utils.plot import bar_plot
from test_looper.utils.services import run_tests


# globals
# for now we let all the slots be global TODO?
# TODO: much of this will be set by odb
class defaultRepo:
    name = "template_repo"


repo_slot = cells.Slot(defaultRepo())


class defaultBranch:
    name = "none"
    top_commit = None


branch_slot = cells.Slot(defaultBranch())

class defaultCommit:
    sha = "none"

commit_slot = cells.Slot(defaultCommit())


class TLService(ServiceBase):
    def initialize(self):
        self.db.subscribeToSchema(test_looper_schema)
        # set the corresponding repo_slot

    def doWork(self, shouldStop):
        while not shouldStop.is_set():
            # wake up every 100ms and look at the objects in the ODB.
            time.sleep(.1)

            with self.db.transaction():

                result = TestResults.lookupAll()
                for n in result:
                    print((n.name, n.testsDefined, n.needsMoreWork))
                    if n.timestamp < time.time() - n.lifetime:
                        # this will actually delete the object from the ODB.
                        n.delete()

    @staticmethod
    def serviceDisplay(serviceObject, instance=None, objType=None,
                       queryArgs=None):
        # make sure cells has loaded these classes in the database and
        # subscribed to all the objects.
        cells.ensureSubscribedSchema(test_looper_schema)

        return cells.VCenter(
            cells.ResizablePanel(
                cells.FillSpace(
                    selections_card(), horizontal="center", vertical="top"),
                cells.ResizablePanel(
                    cells.FillSpace(
                        test_results_table(), horizontal="center",
                        vertical="top"
                    ),
                    cells.FillSpace(
                        plots_card(), horizontal="center", vertical="top"
                    ),
                    split="horizontal"
                )
            )
        )


# helper functions

# Reporting ###
# I display test run resports #
def test_results_table():
    column = ['id', 'name', 'success', 'startTime', 'executionTime']
    results = []
    for tr in TestResults.lookupAll():
        for tcr in tr.results:
            results.append(tcr)
    return cells.Card(
         cells.Scrollable(
             cells.Table(
                 colFun=lambda: column,
                 rowFun=lambda: results,
                 headerFun=lambda x: x,
                 # rendererFun=lambda w, field: cells.Popover(
                 #    f"{field} {w}", "title", "detail"),
                 rendererFun=test_results_table_render_fun(),
                 maxRowsPerPage=50,
                 sortColumn="name",
                 sortColumnAscending=True,
             )
         ),
         header="Test reporting",
         padding=5
    )


def test_results_table_render_fun():
    return lambda result, col: (
        result.testId if col == 'id' else
        result.testName if col == 'name' else
        result.success if col == 'success' else
        result.startTime if col == 'startTime' else
        result.executionTime
    )


# Plots & Graphs ###
def plots_card():
    results = []
    for tr in TestResults.lookupAll():
        for tcr in tr.results:
            results.append(tcr)
    x = range(len(results))
    y = [r.executionTime/1000 for r in results]
    return cells.Card(
        cells.Subscribed(
            lambda: cells.WebglPlot(
                lambda: bar_plot(
                    x, y, width=0.2, color="blue"
                ).withBottomAxis(
                    label="tests"
                ).withLeftAxis(
                    label="elapsed time in seconds"
                ).withMouseoverFunction(plot_hover)
            )
        ),
        header="Tests Overview",
        padding=5
    )


def plot_hover(x, y, screenRect):
    return [
        Plot.MouseoverLegend(
            x=x, y=y, contents=[[Plot.Color(blue=255, alpha=255), y]]
        )
    ]


# Selections ###
# Branches and Dropdowns
def selections_card():
    padding = cells.Padding(5)
    return cells.Highlighted(
        cells.Card(
            cells.SingleLineTextBox(
                repo_slot.get().name,
                onEnter=lambda text: repo_slot.set(
                    Repository.lookupOne(name=text)
                )
            ) +
            cells.HorizontalSequence(
                [
                    cells.Card(
                        cells.FillSpace(
                            padding * cells.Subscribed(
                                lambda: cells.Dropdown(
                                    f'Git branch: {branch_slot.get().name}',
                                    [b.name for b in Branch.lookupAll()],
                                    lambda i: _branch_setter(i)
                                )
                            ) +
                            padding * cells.FillSpace(
                                cells.Subscribed(
                                    lambda: cells.Dropdown(
                                        "Git commit: " + str(
                                            commit_slot.get().sha),
                                        _commit_getter(),
                                        lambda i:_commit_setter(i)
                                    )
                                )
                            ) +
                            padding * cells.Button(
                                cells.HCenter("run"),
                                lambda: run_tests(
                                    'localhost', '8080', 'TOKEN'
                                ),
                                style="primary",
                            ) +
                            padding * cells.Button(
                                cells.HCenter("clear"),
                                lambda: None,
                                style="primary",
                            )
                        )
                    ),
                    cells.Card(
                        cells.FillSpace(
                            cells.Subscribed(lambda: info_panel())
                        )
                    ),
                ]
            ),
            header="Branch and commit selection",
            padding=5
        ), color="lightblue"
    )


def info_panel():
    # TODO: sort out how to really deal with commits
    sha = commit_slot.get().sha
    try:
        commit = Commit.lookupOne(sha=sha)
        repo = Repository.lookupOne(name=repo_slot.get().name)
        info = (cells.Text(f'author name: {commit.author_name}') +
                cells.Text(f'author_email: {commit.author_email}') +
                cells.Text(f'summary: {commit.summary}') +
                cells.Text(f'parents: {commit.parents}')
                )
    except TypeError:
        info = cells.Text("Please select a repo & commit")
    return cells.Center(
        info
    )


# random helper function: TODO remove
# this is all for testing, will happen in ODB
def _commit_setter(sha):
    commit_slot.set(Commit.lookupOne(sha=sha))

def _commit_getter():
    top_commit = branch_slot.get().top_commit
    if top_commit is None:
        return []
    else:
        commits = [c.sha for c in top_commit.parents]
        commits.append(top_commit.sha)
        return commits

def _branch_setter(name):
    branch = Branch.lookupOne(name=name)
    branch_slot.set(branch)
    commit_slot.set(branch.top_commit)
