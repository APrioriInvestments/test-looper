from collections import defaultdict
from functools import partial
import logging

from object_database import ServiceBase
import object_database.web.cells as cells

from testlooper.utils import setup_logger
from testlooper.schema.schema import engine_schema, test_schema, repo_schema, ui_schema

logger = setup_logger(__name__, level=logging.INFO)


class SchemaMonitorService(ServiceBase):
    """
    This service uses a generic schema monitor that subscribes to some schemas, and shows
    you what objects could exist, and what objects do exist.

    Lets you check performance, ODB model coherency, etc.
    """

    schemas = [engine_schema, test_schema, repo_schema, ui_schema]

    def initialize(self):
        logger.info("Initializing SchemaMonitorService")
        self.db.subscribeToSchema(*SchemaMonitorService.schemas)

    @staticmethod
    def serviceDisplay(service_object, instance=None, objType=None, queryArgs=None):
        """Make a tab for each schema object, then a table of all live objects
        and their properties.
            _types holds a string to class mapping
            _field_types holds a name to {field, type} mapping
        """
        isExpanded = defaultdict(lambda: cells.Slot(False))  # assumes unique obj names

        def makeColFun(schema, obj_name):
            return lambda: ["_identity"] + list(schema._field_types[obj_name].keys())

        def makeRowFun(obj):
            return lambda: obj.lookupAll()

        def makeTable(schema, obj_name, obj):
            if isExpanded[obj_name].get():
                return cells.Table(
                    colFun=makeColFun(schema, obj_name),
                    rowFun=makeRowFun(obj),
                    headerFun=lambda x: x,
                    rendererFun=lambda data, field: cells.Text(str(getattr(data, field))),
                    maxRowsPerPage=50,
                )

        def toggle(obj_name):
            isExpanded[obj_name].toggle()

        tabs = []
        for schema in SchemaMonitorService.schemas:
            cells.ensureSubscribedSchema(schema)
            schema_layout = cells.Padding()  # placeholder
            for obj_name, obj in schema._types.items():
                # bind the object to a partial function, otherwise it will point to obj_name
                # and every table will point to the last obj_name in the loop
                panel = cells.Panel(
                    cells.Button(obj_name, partial(toggle, obj_name))
                    + cells.Subscribed(partial(makeTable, schema, obj_name, obj))
                )
                schema_layout += panel

            tabs.append((schema.name, cells.Scrollable(schema_layout)))

        return cells.Tabs(tabs)
