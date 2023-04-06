import object_database.web.cells as cells
import time

from object_database import ServiceBase
from .schema import test_looper_schema
from .query_args import QueryArgs

# define a type of entry in odb. We'll have one instance of this class for each
# message in the database
@test_looper_schema.define
class Message:
    timestamp = float
    message = str
    lifetime = float


class TestlooperService(ServiceBase):
    def initialize(self):
        # make sure we're subscribed to all objects in our schema.
        self.db.subscribeToSchema(test_looper_schema)

    def doWork(self, shouldStop):
        # this is the main entrypoint for the service - it gets to do work here.
        while not shouldStop.is_set():
            # wake up every 100ms and look at the objects in the ODB.
            time.sleep(.1)

            # delete any messages more than 10 seconds old
            with self.db.transaction():
                # get all the messages
                messages = Message.lookupAll()

                for m in messages:
                    if m.timestamp < time.time() - m.lifetime:
                        # this will actually delete the object from the ODB.
                        m.delete()

    @staticmethod
    def serviceDisplay(serviceObject, instance=None, objType=None, queryArgs=None):
        # big assumption - this only gets called once.
        
        print('---------------calling serviceDisplay---------------')

        reload_button = cells.Button('Reload', reload)



        # check the queryArgs to see if we should jump to somewhere.
        if queryArgs:
            qargs = QueryArgs(queryArgs)
            page_type = qargs.current_page
            # probably there is a better way then checking every type
            if page_type == 'repo':
                return cells.Panel(reload_button + cells.Card('Repo page'))
            elif page_type == 'branch':
                return cells.Panel(reload_button + cells.Card('Branch page'))
            elif page_type == 'commit':
                return cells.Panel(reload_button + cells.Card('Commit page'))
            else:
                raise ValueError('unexpected page type ', page_type)
        else:
            return cells.Panel(reload_button + cells.Card('Main page'))

    
        # make sure cells has loaded these classes in the database and subscribed
        # to all the objects.
        cells.ensureSubscribedSchema(test_looper_schema)

        



        def newMessage():
            # calling the constructor creates a new message object. Even though we
            # orphan it immediately, we can always get it back by calling
            #       Message.lookupAll()
            # because ODB objects have an explicit lifetime (they have to be destroyed)
            Message(timestamp=time.time(), message=editBox.currentText.get(), lifetime=20)

            # reset our edit box so we can type again
            editBox.currentText.set("")

        # define an 'edit box' cell. The user can type into this.
        editBox = cells.SingleLineTextBox(onEnter=lambda newText: newMessage())


        # 
        #









        return  cells.Panel(
            editBox >> cells.Button(
                "New Message",
                newMessage
            )
        ) + cells.Panel(
            cells.Table(
                colFun=lambda: ['timestamp', 'lifetime', 'message'],
                rowFun=lambda: sorted(Message.lookupAll(), key=lambda m: -m.timestamp),
                headerFun=lambda x: x,
                rendererFun=lambda m, col: cells.Subscribed(
                    lambda:
                    cells.Timestamp(m.timestamp) if col == 'timestamp' else
                    m.message if col == 'message' else
                    cells.Dropdown(
                        m.lifetime,
                        [1, 2, 5, 10, 20, 60, 300],
                        lambda val: setattr(m, 'lifetime', val)
                    )
                ),
                maxRowsPerPage=100,
                fillHeight=True
            )
         ) + cells.Border(border=100) * cells.Panel(cells.Button('Hello', lambda: print('hello')))

def reload():
    import os
    os._exit(0)

