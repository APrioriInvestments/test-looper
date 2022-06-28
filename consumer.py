import time

from object_database import connect, Schema

from test_looper.schema import *

db = connect('localhost', 8000, 'TOKEN')
db.subscribeToSchema(test_looper_schema)


ts = 0
while True:
    with db.view():
        nodes = TestNode.lookupAll()
        for n in nodes:
            print((n.name, n.testsDefined, n.needsMoreWork))
    time.sleep(1)
