import time

import object_database.web.cells as cells
from object_database import connect, ServiceBase
from object_database.web.cells.webgl_plot import Plot

from .schema import test_looper_schema, TestNode


# globals
# for now we let all the slots be global TODO?
# TODO: much of this will be set by odb
repo_slot = cells.Slot(
    {
        "name": "test-looper",
        "url": "https://github.com/APrioriInvestments/test-looper"
    }
)
branch_slot = cells.Slot("none")
available_branches_slot = cells.Slot(
    ["{}_branch_{}".format("test-looper", i) for i in range(10)]
)
available_commits_slot = cells.Slot(
    ["commit_{}".format(i) for i in range(10)]
)
commit_slot = cells.Slot(
    {
        "summary": "",
        "author_name": "",
        "author_email": "",
        "sha": ""
     }
)


class TLService(ServiceBase):
    def initialize(self):
        self.db.subscribeToSchema(test_looper_schema)

    def doWork(self, shouldStop):
        while not shouldStop.is_set():
            # wake up every 100ms and look at the objects in the ODB.
            time.sleep(.1)

            with self.db.transaction():
                nodes = TestNode.lookupAll()
                for n in nodes:
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
                )
            )
        )


# helper functions

# Reporting ###
# I display test run resports #
def test_results_table():
    return cells.Card(
        cells.Highlighted(
            cells.Table(
                colFun=lambda: ['name', 'testsDefined', 'needsMoreWork'],
                rowFun=lambda: TestNode.lookupAll(),
                headerFun=lambda x: x,
                rendererFun=test_results_table_render_fun(),
                maxRowsPerPage=100,
                fillHeight=True
                ), color="lightblue"
        ),
        header="Test reporting",
        padding=5
    )


def test_results_table_render_fun():
    return lambda n, col: cells.Subscribed(
        lambda:
            n.name if col == 'name' else
            n.testsDefined if col == 'testsDefined'
        else n.needsMoreWork)


# Plots & Graphs ###
def plots_card():
    return cells.Card(
        cells.Highlighted(
            cells.WebglPlot(lambda: Plot.create([1, 2, 3], [1, 2, 3])),
            color="lightblue"
        ),
        header="Tests Overview",
        padding=5
    )


# Selections ###
# Branches and Dropdowns
def selections_card():
    return cells.Highlighted(
        cells.Card(
            cells.SingleLineTextBox(
                repo_slot.get()["url"],
                onEnter=lambda text: repo_slot.set({"url": text})
            ) +
            cells.HorizontalSequence(
                [
                    cells.Card(
                        cells.FillSpace(
                            cells.Subscribed(
                                lambda: cells.Dropdown(
                                    "Git branch: " + str(branch_slot.get()),
                                    available_branches_slot.get(),
                                    lambda i: branch_slot.set(i)
                                )
                            ) +
                            cells.FillSpace(
                                cells.Subscribed(
                                    lambda: cells.Dropdown(
                                        "Git commit: " + str(
                                            commit_slot.get()['sha']),
                                        available_commits_slot.get(),
                                        lambda i:_commit_setter(i)
                                    )
                                )
                            )
                        )
                    ),
                    cells.Card(
                        cells.FillSpace(
                            info_panel()
                        )
                    ),
                ]
            ),
            header="Branch and commit selection",
            padding=5
        ), color="lightblue"
    )


def info_panel():
    return cells.Subscribed(
            lambda: cells.FillSpace(
                cells.Text(
                    "summary:\n" + str(commit_slot.get()["summary"])
                ) +
                cells.FillSpace(
                    cells.Text(
                        "author: " + str(commit_slot.get()["author_name"])
                    )
                )
            )
    )


# random helper function: TODO remove
# this is all for testing, will happen in ODB
def _commit_setter(i):
    data = {
        "summary": "summary for commit {}".format(i),
        "author_name": "author for commit {}".format(i),
        "author_email": "email for commit {}".format(i),
        "sha": "sha_for_commit_{}".format(i)
    }
    commit_slot.set(data)
