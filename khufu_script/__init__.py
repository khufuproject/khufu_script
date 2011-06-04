from ConfigParser import SafeConfigParser
import argparse
import os
import code
import logging

import clue_script

import clue_sqlaloader

from pyramid.util import DottedNameResolver
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.schema import ForeignKeyConstraint, DropConstraint

from weberror.evalexception import make_eval_exception
from weberror.errormiddleware import make_error_middleware
from weberror.errormiddleware import formatter


maybe_resolve = DottedNameResolver(None).maybe_resolve


def update_dict(parser, section, d):
    '''Update the given dictionary, d, with all keys/values
    from the section in the config parser specified.
    '''

    if parser.has_section(section):
        for k in parser.options(section):
            d[k] = parser.get(section, k)
    return d


class FreshDBCommand(object):
    '''Empty the database (if needed) and load up proper
    tables and initial data.
    '''

    __name__ = 'freshdb'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        parser = self.manager._argparser_factory(prog=self.__name__)
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Run with debugging turned on')
        ns = parser.parse_args(argv)
        if ns.debug:
            clue_sqlaloader.logger.setLevel(logging.DEBUG)
            self.logger.setLevel(logging.DEBUG)

        dirname = self.manager.initial_data_dir
        settings = self.manager.settings

        argv = list(argv)
        if '--remove' not in argv:
            argv.append('--remove')
        self.manager.syncdb(*argv)

        for x in os.listdir(dirname):
            if not x.endswith('.yaml'):
                continue

            filename = os.path.join(dirname, x)
            short = filename
            if short.startswith(os.getcwd()):
                short = short[len(os.getcwd()):]
            clue_sqlaloader.load(settings['sqlalchemy.url'], filename)
            self.logger.info('Loaded: %s' % short)


class SyncDBCommand(object):
    '''Ensure all database tables exist
    '''

    __name__ = 'syncdb'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        '''Make sure all database tables exist'''

        parser = self.manager._argparser_factory(prog=self.__name__)
        parser.add_argument('tables', metavar='table',
                            help='Tables to operate on', nargs='*',
                            default=['*'])
        parser.add_argument('-r', '--remove', action='store_true',
                            help='Remove tables before syncing',
                            default=False)
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Run with debugging turned on')
        ns = parser.parse_args(argv)

        settings = self.manager.settings
        self.logger.info('Accessing database: %s'
                         % settings['sqlalchemy.url'])
        engine = self.manager._create_engine(settings['sqlalchemy.url'])
        dbmeta = self.manager._create_metadata()
        dbmeta.reflect(engine)
        dbtables = dict(dbmeta.tables)

        pending_to_add = []
        pending_to_remove = []
        for metadata in self.manager.db_metadatas:
            metadata = maybe_resolve(metadata)

            if '*' in ns.tables:
                tables = dict(metadata.tables)
            else:
                tables = dict((k, v)
                              for k, v in metadata.tables.items()
                              if k in ns.tables)

            if ns.remove:
                for t in tables:
                    if t in dbtables:
                        pending_to_remove.append(dbtables.pop(t))
                        self.logger.debug('Flagged for removal: %s' % t)

            tables = dict((k, v) for k, v in tables.items()
                          if k not in dbtables)

            if len(tables) > 0:
                pending_to_add += tables.values()

        if len(pending_to_remove) > 0:
            dbmeta = self.manager._create_metadata()
            tables = []
            constraints = []
            for table in pending_to_remove:
                fkcs = []
                for fk in table.foreign_keys:
                    fkcs.append(ForeignKeyConstraint(
                            (), (), fk.constraint.name))
                table = Table(table.name, dbmeta, *fkcs)
                constraints.extend(fkcs)
                tables.append(table)

            try:
                for constraint in constraints:
                    engine.execute(DropConstraint(constraint))
                    name = getattr(constraint, 'name', '(no name)')
                    self.logger.debug('Dropped foreign key constraint: %s'
                                      % name)
                self.logger.info('removed %i constraints'
                                 % len(constraints))
            except Exception, ex:
                self.logger.warn('Constraints could not be removed: %s'
                                 % str(ex))

            dbmeta.drop_all(bind=engine, tables=tables)
            self.logger.info('removed %i tables' % len(pending_to_remove))

        if len(pending_to_add) > 0:
            dbmeta = self.manager._create_metadata()
            tables = [x.tometadata(dbmeta) for x in pending_to_add]
            dbmeta.create_all(bind=engine, tables=tables)
            self.logger.info('added %i tables' % len(pending_to_add))


class LoadDataCommand(object):
    '''Add data based on the YAML from filename'''

    __name__ = 'loaddata'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        parser = self.manager._argparser_factory(prog=self.__name__)
        parser.add_argument('filenames', metavar='file',
                            help='Files to load', nargs='+')
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Run with debugging turned on')
        ns = parser.parse_args(argv)

        settings = self.manager.settings
        self.manager.syncdb()

        if ns.debug:
            clue_sqlaloader.logger.setLevel(logging.DEBUG)

        for filename in ns.filenames:
            clue_sqlaloader.load(settings['sqlalchemy.url'], filename)
            self.logger.info('Loaded: %s' % filename)


class ShellCommand(object):
    '''Launch a Python shell
    '''

    __name__ = 'shell'

    interact = staticmethod(code.interact)

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        import sys
        from pyramid.scripting import get_root

        parser = self.manager._argparser_factory(prog=self.__name__)
        parser.parse_args(argv)

        banner = '''\
Python %s on %s
Type "help" for more information.

dir() =>
    registry  - the active Pyramid registry
    root      - the traversal root
    app       - the active wsgi application
''' % (sys.version, sys.platform)
        app = self.manager.make_app({}, **self.manager.settings)
        innerapp = self.get_app_with_registry(app)
        root, closer = get_root(innerapp)
        shell_globals = {'root': root,
                         'registry': innerapp.registry,
                         'app': app}
        self.interact(banner, local=shell_globals)

    def get_app_with_registry(self, app, count=0):
        if count > 10:
            return None

        if hasattr(app, 'registry'):
            return app
        elif hasattr(app, 'app'):
            return self.get_app_with_registry(app.app, count + 1)
        elif hasattr(app, 'application'):
            return self.get_app_with_registry(app.application, count + 1)


class ManagerRunner(object):
    '''Container for the possible commands to run.
    '''

    DEFAULT_SETTINGS = {
        'reload_templates': True,
        'DEBUG': True,
        'debug_templates': True,
        }

    name = 'manage'
    config_filename = name + '.ini'

    def __init__(self, name, app_factory, db_metadatas=[],
                 config_filename=None, default_settings=None,
                 logger=None, initial_data_dir=None):
        self.name = name
        self.app_factory = maybe_resolve(app_factory)
        self.config_filename = config_filename or (name + '.ini')
        self.db_metadatas = db_metadatas

        self.default_settings = default_settings = \
            dict(default_settings or {})
        for k, v in self.DEFAULT_SETTINGS.items():
            default_settings.setdefault(k, v)

        if logger is None:
            logger = logging.getLogger(self.name)

        if isinstance(logger, basestring):
            self.logger = logging.getLogger(logger)
        else:
            self.logger = logger

        self.initial_data_dir = initial_data_dir

    _exists = staticmethod(os.path.exists)
    _config_parser_factory = SafeConfigParser
    _argparser_factory = argparse.ArgumentParser

    @property
    def settings(self):
        if hasattr(self, '_settings'):
            return self._settings

        settings = dict(self.default_settings)
        self._settings = settings
        if self._exists(self.config_filename):
            self.logger.info('Retrieving settings: %s'
                             % self.config_filename)
            parser = self._config_parser_factory()
            parser.read([self.config_filename])
            update_dict(parser, self.name, settings)
            self.logger.info('Data source: sqlalchemy -> %s'
                             % settings.get('sqlalchemy.url', 'N/A'))
        return settings

    _create_engine = staticmethod(create_engine)
    _create_metadata = MetaData

    def report(self, exc_info):
        m = '\n'.join(formatter.format_text(exc_info))
        self.logger.error(m)

    def make_app(self, global_conf={}):
        settings = self.settings
        app = maybe_resolve(self.app_factory)(global_conf, **settings)
        if settings.get('DEBUG', False):
            app = make_eval_exception(app, global_conf, reporters=[self])
        else:
            app = make_error_middleware(app, global_conf)

        return app

    @property
    def commander(self):
        if hasattr(self, '_commander'):
            return self._commander

        commander = self._commander = clue_script.Commander()

        runserver = clue_script.make_reloadable_server_command(self.make_app)
        runserver.parser.set_defaults(with_reloader=True)
        commander.add(runserver)

        commander.add(LoadDataCommand(self))
        commander.add(ShellCommand(self))

        if self.db_metadatas:
            commander.add(SyncDBCommand(self))
        if self.initial_data_dir:
            commander.add(FreshDBCommand(self))

        return self._commander

    def main(self):
        logging.basicConfig()
        self.logger.setLevel(logging.INFO)
        self.commander.run()


make_manager = ManagerRunner
