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

        return cells.ResizablePanel(
            selections_card(),
            cells.ResizablePanel(
                test_results_table(),
                plots_card()
            )
        )


# helper functions

### Reporting ###
# I display test run resports #
def test_results_table():
    return cells.Card(
        cells.Panel(
        cells.Table(
            colFun=lambda: ['name', 'testsDefined', 'needsMoreWork'],
            rowFun=lambda: TestNode.lookupAll(),
            headerFun=lambda x: x,
            rendererFun=test_results_table_render_fun(),
            maxRowsPerPage=100,
            fillHeight=True
            )
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

### Plots & Graphs ###
def plots_card():
    return cells.Card(
        cells.Panel(
            cells.WebglPlot(lambda: Plot.create([1, 2, 3], [1, 2, 3]))
        ),
        header="Tests Overview",
        padding=5
    )

### Selections ###
# Branches and Dropdowns
def selections_card():
    branch_slot = cells.Slot("dev")
    commit_slot = cells.Slot("last commit")
    return cells.Card(
        cells.Panel(
            cells.Subscribed(
                lambda: cells.Dropdown(
                    "Git branch: " + str(branch_slot.get()),
                    ["branch1", "branch2", "branch3"],
                    lambda i: branch_slot.set(i)
                )
            ) +
            cells.Subscribed(
                lambda: cells.Dropdown(
                    "Git commit: " + str(commit_slot.get()),
                    ["commit1", "commit2", "commit3"],
                    lambda i: commit_slot.set(i)
                )
            )
        ),
        header="Branch and commit selection",
        padding=5
    )

