import unittest


class MainTests(unittest.TestCase):

    def setUp(self):
        from khufu_script import ManagerRunner

        def app_factory(global_conf, **settings):
            return {'global_conf': global_conf, 'settings': settings}

        class MockManagerRunner(ManagerRunner):
            sample_settings = {'MainTests': {'foo': 'bar'}}

            def __init__(self, **kwargs):
                params = dict(name='MainTests',
                              app_factory=app_factory)
                params.update(kwargs)
                ManagerRunner.__init__(self, **params)

            def info(self, *args, **kwargs):
                pass

            def _config_parser_factory(self):
                return self

            def _argparser_factory(self, *args, **kwargs):
                return self

            def _create_engine(self, *args, **kwargs):
                return self

            def add_argument(self, *args, **kwargs):
                pass

            def parse_args(self, argv):
                return object()

            def read(self, filename):
                pass

            def has_section(self, s):
                return s in self.sample_settings

            def options(self, s):
                return self.sample_settings[s].keys()

            def get(self, s, k):
                return self.sample_settings[s][k]

            def _create_metadata(self, *args, **kwargs):
                return self

            def reflect(self, bind=None):
                return None

            @property
            def tables(self):
                return []

        self.runner_factory = MockManagerRunner

    def test_init(self):
        import logging

        runner = self.runner_factory(logger=None)
        self.assertEqual(runner.logger.name, runner.name)

        runner = self.runner_factory(logger='foo')
        self.assertEqual(runner.logger.name, 'foo')

        runner = self.runner_factory(logger=logging.getLogger('bar'))
        self.assertEqual(runner.logger.name, 'bar')

    def test_load_settings(self):
        runner = self.runner_factory()
        self.assertEqual(runner.load_settings()['DEBUG'], True)

        runner._exists = lambda x: True
        self.assertEqual(runner.load_settings()['foo'], 'bar')

    def test_syncdb(self):
        runner = self.runner_factory()
        runner.db_metadatas = [runner]
        runner.sample_settings['sqlalchemy.url'] = 'foo'
        runner.logger = runner
        runner.load_settings = lambda: {'sqlalchemy.url': 'foo'}
        runner.syncdb()
