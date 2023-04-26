from object_database import Schema

# schema for test-looper repository objects
repo_schema = Schema("testlooper_repo")

# schema for test-looper test objects
test_schema = Schema("test_looper_test")

# schema for test-looper engine
engine_schema = Schema("test_looper_engine")

# schema for test-looper's UI
# We will probably get rid of this when we implement the dedicated
# TestLooper Flask UI
ui_schema = Schema("testlooper_ui")
