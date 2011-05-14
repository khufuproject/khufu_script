from ConfigParser import SafeConfigParser
import argparse
import os
import code
import logging

import clue_script
from pyramid.util import DottedNameResolver
import sqlalchemy.schema
from sqlalchemy import create_engine, MetaData

from weberror.evalexception import make_eval_exception
from weberror.errormiddleware import make_error_middleware
from weberror.errormiddleware import formatter


maybe_resolve = DottedNameResolver(None).maybe_resolve


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
        parser.add_argument('-d', '--delete', action='store_true',
                            help='Delete tables before syncing',
                            default=False)
        ns = parser.parse_args(argv)

        settings = self.manager.load_settings()
        self.logger.info('Accessing database: %s'
                         % settings['sqlalchemy.url'])
        engine = self.manager._create_engine(settings['sqlalchemy.url'])

        dbmeta = self.manager._create_metadata()
        dbmeta.reflect(bind=engine)
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

            if ns.delete:
                for t in tables:
                    if t in dbtables:
                        table = dbtables.pop(t)
                        pending_to_remove.append(table)
                        self.logger.debug('Flagged for removal: %s' % t)

            tables = dict((k, v) for k, v in tables.items()
                          if k not in dbtables)

            if len(tables) > 0:
                pending_to_add += tables.values()

        if len(pending_to_remove) > 0:
            self.logger.info('removed %i tables' % len(pending_to_remove))
            dbmeta = self.manager._create_metadata()
            tables = []
            all_fkcs = []
            for table in pending_to_remove:
                fkcs = []
                for fk in table.foreign_keys:
                    if not fk.name:
                        continue
                    fkc = sqlalchemy.schema.ForeignKeyConstraint((), (),
                                                                 name=fk.name)
                    fkcs.append(fkc)
                table = sqlalchemy.schema.Table(table.name, dbmeta, *fkcs)
                all_fkcs.extend(fkcs)
                tables.append(table)

            # TODO: fix dropping foreign key constraints
            # for fkc in all_fkcs:
            #     engine.execute(sqlalchemy.schema.DropConstraint(fkc))
            #     logger.info('Dropped foreign key constraint: %s' % fkc)

            dbmeta.drop_all(bind=engine, tables=tables)

        if len(pending_to_add) > 0:
            self.logger.info('added %i tables' % len(pending_to_add))
            dbmeta = self.manager._create_metadata()
            tables = [x.tometadata(dbmeta) for x in pending_to_add]
            dbmeta.create_all(bind=engine, tables=tables)


class LoadDataCommand(object):
    '''Add data based on the YAML from filename'''

    __name__ = 'loaddata'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        from clue_sqlaloader import load, logger

        parser = self.manager._argparser_factory(prog=self.__name__)
        parser.add_argument('filenames', metavar='file',
                            help='Files to load', nargs='+')
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Run with debugging turned on')
        ns = parser.parse_args(argv)

        settings = self.manager.load_settings()
        self.manager.syncdb()

        if ns.debug:
            logger.setLevel(logging.DEBUG)

        for filename in ns.filenames:
            load(settings['sqlalchemy.url'], filename)
            logger.info('Loaded: %s' % filename)


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
        app = self.manager.make_app({}, **self.manager.load_settings())
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
                 config_filename=None, settings=None,
                 logger=None):
        self.name = name
        self.app_factory = maybe_resolve(app_factory)
        self.config_filename = config_filename or (name + '.ini')
        self.db_metadatas = db_metadatas

        self.settings = settings = dict(settings or {})
        for k, v in self.DEFAULT_SETTINGS.items():
            settings.setdefault(k, v)

        if logger is None:
            logger = logging.getLogger(self.name)

        if isinstance(logger, basestring):
            self.logger = logging.getLogger(logger)
        else:
            self.logger = logger

        self.syncdb = SyncDBCommand(self)
        self.loaddata = LoadDataCommand(self)
        self.shell = ShellCommand(self)

    _exists = staticmethod(os.path.exists)
    _config_parser_factory = SafeConfigParser
    _argparser_factory = argparse.ArgumentParser

    def load_settings(self):
        settings = dict(self.settings)
        if self._exists(self.config_filename):
            self.logger.info('Retrieving settings: %s'
                             % self.config_filename)
            parser = self._config_parser_factory()
            parser.read([self.config_filename])
            if parser.has_section(self.name):
                for k in parser.options(self.name):
                    settings[k] = parser.get(self.name, k)
        return settings

    _create_engine = staticmethod(create_engine)
    _create_metadata = MetaData

    def report(self, exc_info):
        m = '\n'.join(formatter.format_text(exc_info))
        self.logger.error(m)

    def make_app(self, global_conf, **settings):
        app = maybe_resolve(self.app_factory)(global_conf, **settings)
        if settings.get('DEBUG', False):
            app = make_eval_exception(app, global_conf, reporters=[self])
        else:
            app = make_error_middleware(app, global_conf)

        return app

    def main(self):
        logging.basicConfig()
        self.logger.setLevel(logging.INFO)

        def _make_app():
            global_conf = {}
            settings = dict(self.load_settings())

            return self.make_app(global_conf, **settings)

        runserver = clue_script.make_reloadable_server_command(_make_app)
        runserver.parser.set_defaults(with_reloader=True)
        commands = [
            runserver,
            clue_script.PseudoCommand(self.loaddata),
            clue_script.PseudoCommand(self.shell),
            ]
        if self.db_metadatas:
            commands.append(clue_script.PseudoCommand(self.syncdb))

        commander = clue_script.Commander(commands)
        commander.run()


make_manager = ManagerRunner
