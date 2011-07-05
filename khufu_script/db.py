import clue_sqlaloader
from sqlalchemy import Table
from sqlalchemy.schema import ForeignKeyConstraint, DropConstraint
import os
import sys
import logging

from .utils import maybe_resolve

prog_prefix = os.path.basename(sys.argv[0])


class FreshDBCommand(object):
    '''Empty the database (if needed) and load up proper
    tables and initial data.
    '''

    __name__ = 'freshdb'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        prog = prog_prefix + ' ' + self.__name__
        parser = self.manager._argparser_factory(prog=prog,
                                                 description=self.__doc__)
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
        SyncDBCommand(self.manager).syncdb(remove=True)

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
    '''Ensure all database tables exist and upgrade the database
    to support latest version.
    '''

    __name__ = 'syncdb'

    def __init__(self, manager, upgradedb=None):
        self.manager = manager
        self.logger = manager.logger
        self.upgradedb = upgradedb

    def __call__(self, *argv):
        '''Make sure all database tables exist'''

        prog = prog_prefix + ' ' + self.__name__
        parser = self.manager._argparser_factory(prog=prog,
                                                 description=self.__doc__)
        parser.add_argument('tables', metavar='table',
                            help='Tables to operate on', nargs='*',
                            default=['*'])
        parser.add_argument('-r', '--remove', action='store_true',
                            help='Remove tables before syncing',
                            default=False)
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Run with debugging turned on')
        ns = parser.parse_args(argv)

        self.syncdb(ns.tables, ns.remove)

    def syncdb(self, table_names=['*'], remove=False):
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

            if '*' in table_names:
                tables = dict(metadata.tables)
            else:
                tables = dict((k, v)
                              for k, v in metadata.tables.items()
                              if k in table_names)

            if remove:
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

        if self.upgradedb != None:
            self.upgradedb()


class LoadDataCommand(object):
    '''Add data based on the YAML from filename'''

    __name__ = 'loaddata'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def __call__(self, *argv):
        prog = prog_prefix + ' ' + self.__name__
        parser = self.manager._argparser_factory(prog=prog,
                                                 description=self.__doc__)
        parser.add_argument('filenames', metavar='file',
                            help='Files to load', nargs='+')
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Run with debugging turned on')
        ns = parser.parse_args(argv)

        settings = self.manager.settings
        SyncDBCommand(self.manager).syncdb(remove=False)

        if ns.debug:
            clue_sqlaloader.logger.setLevel(logging.DEBUG)

        for filename in ns.filenames:
            clue_sqlaloader.load(settings['sqlalchemy.url'], filename)
            self.logger.info('Loaded: %s' % filename)


class UpgradeDBCommand(object):
    '''Perform an upgrade on the database.
    '''

    __name__ = 'upgradedb'

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

        try:
            import migrate
        except ImportError, e:
            raise ImportError(str(e) + ': Please install SQLAlchemy-migrate')

    def __call__(self, *argv):
        self.upgradedb()

    def upgradedb(self):
        from migrate.versioning.api import (upgrade, version_control,
                                            db_version, version)
        from migrate.exceptions import DatabaseNotControlledError
        from migrate.versioning.repository import Repository

        sql_url = self.manager.settings['sqlalchemy.url']
        upgraded = []
        for mod in self.manager.db_migrations:
            mname = str(mod)
            try:
                mod = maybe_resolve(mname)
            except ImportError:
                self.logger.warn('Skipping upgrade, repo doesn'
                                 '\'t exist - %s' % mname)
                continue

            p = mod.__path__[0]
            repo = Repository(p)
            new = repo.latest

            try:
                old = db_version(sql_url, p)
            except DatabaseNotControlledError:
                self.logger.warn('DB missing version info, '
                                 'updating - %s' % repo.id)
                version_control(sql_url, p, version(p))
                old = db_version(sql_url, p)

            if new <= old:
                self.logger.debug('Upgrade not required - %s (%s)'
                                  % (repo.id, old))
                continue

            try:
                upgrade(sql_url, p)
                self.logger.info('Upgraded %s: %s to %s' % (repo.id, old, new))
                upgraded.append(repo)
            except DatabaseNotControlledError:
                self.logger.warn('DB missing version info, '
                                 'updating - %s' % repo.id)
                version_control(sql_url, p)
        self.logger.info('Updated db schema for %i components' % len(upgraded))
