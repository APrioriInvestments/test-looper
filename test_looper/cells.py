import time

import object_database.web.cells as cells
from object_database import connect, ServiceBase

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

        slot = cells.Slot("dev")

        return cells.SplitView(
            [
                (cells.Card(
                    cells.Subscribed(lambda:
                        cells.Dropdown(
                            "Git branch: " + str(slot.get()),
                            ["branch1", "branch2", "branch3"],
                            lambda i: slot.set(i)
                        )
                                     )
                ), 1),
                (cells.Card(
                    cells.Table(
                            colFun=lambda: [
                                'name', 'testsDefined', 'needsMoreWork'],
                            rowFun=lambda: TestNode.lookupAll(),
                            headerFun=lambda x: x,
                            rendererFun=renderFun(),
                            maxRowsPerPage=100,
                            fillHeight=True
                    )
                ), 4)
            ]
        )


# helper functions
def renderFun():
    return lambda n, col: cells.Subscribed(
        lambda:
            n.name if col == 'name' else
            n.testsDefined if col == 'testsDefined'
        else "no"
    )
