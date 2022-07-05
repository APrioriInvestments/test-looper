import time

import object_database.web.cells as cells
from object_database import connect, Schema, ServiceBase

from test_looper.schema import *

db = connect('localhost', 8000, 'TOKEN')
db.subscribeToSchema(test_looper_schema)


ts = 0
while True:
    with db.view():
    time.sleep(1)


class TLService(ServiceBase):
    def initialize(self):
        self.db.subscribeToSchema(test_looper_schema)

    def doWork(self, shouldStop):
        while not shouldStop.is_set():
            #wake up every 100ms and look at the objects in the ODB.
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
        cells.ensureSubscribedSchema(schema)


        return cells.Table(
                colFun=lambda: ['name', 'testsDefined', 'needsMoreWork'],
                rowFun=lambda: "row",
                headerFun=lambda x: x,
                rendererFun=lambda n, col: cells.Subscribed(
                    lambda:
                    cells.Timestamp(n.name if col == 'name' else
                    n.testsDefined if col == 'testsDefined' else
                    n.needsMoreWork if col == 'needsMoreWork1' else
                    )
                ),
                maxRowsPerPage=100,
                fillHeight=True
        )
