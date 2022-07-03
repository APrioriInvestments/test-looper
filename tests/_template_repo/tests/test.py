class TestTest:
    @classmethod
    def setup_class(cls):
        return

    def test_success(self):
        assert 1 == 1

    def test_fail(self):
        assert 0 == 1

    @classmethod
    def teardown_class(cls):
        return
