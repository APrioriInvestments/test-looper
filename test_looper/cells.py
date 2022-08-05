import time

import object_database.web.cells as cells
from object_database import connect, ServiceBase
from object_database.web.cells.webgl_plot import Plot

from .schema import test_looper_schema, TestNode


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
    repo_slot = cells.Slot("dev")
    branch_slot = cells.Slot("dev")
    commit_slot = cells.Slot("last commit")
    default_repo_url = "https://github.com/APrioriInvestments/test-looper"
    return cells.Highlighted(
        cells.Card(
            cells.SingleLineTextBox(
                default_repo_url,
                onEnter=lambda text: repo_slot.set(text)
            ) +
            cells.HorizontalSequence(
                [
                    cells.Card(
                        cells.FillSpace(
                            cells.Subscribed(
                                lambda: cells.Dropdown(
                                    "Git branch: " + str(branch_slot.get()),
                                    ["branch1", "branch2", "branch3"],
                                    lambda i: branch_slot.set(i)
                                )
                            ) +
                            cells.FillSpace(
                                cells.Subscribed(
                                    lambda: cells.Dropdown(
                                        "Git commit: " + str(commit_slot.get()
                                                             ),
                                        ["commit1", "commit2", "commit3"],
                                        lambda i: commit_slot.set(i)
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
    is_open = cells.Slot(False)

    return cells.Subscribed(
        lambda: cells.Button(
            "Close" if is_open.get() else "More info",
            lambda: is_open.set(not is_open.get()),
        ) +
        cells.CollapsiblePanel(
            panel=cells.Text("more info about the repo"),
            content=cells.Text(""),
            isExpanded=lambda: is_open.get()
        )
    )
