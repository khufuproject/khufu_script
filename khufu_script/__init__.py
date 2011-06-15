import argparse
import ConfigParser
import logging
import os

import clue_script
import sqlalchemy

from khufu_script import db, shell, utils, wsgi


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
                 logger=None, initial_data_dir=None, db_migrations=[]):
        self.name = name
        self.app_factory = utils.maybe_resolve(app_factory)
        self.config_filename = config_filename or (name + '.ini')
        self.db_metadatas = db_metadatas
        self.db_migrations = db_migrations

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
    _config_parser_factory = ConfigParser.SafeConfigParser
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
            utils.update_dict(parser, self.name, settings)
            self.logger.info('Data source: sqlalchemy -> %s'
                             % settings.get('sqlalchemy.url', 'N/A'))
        return settings

    _create_engine = staticmethod(sqlalchemy.create_engine)
    _create_metadata = sqlalchemy.MetaData

    @property
    def commander(self):
        if hasattr(self, '_commander'):
            return self._commander

        commander = self._commander = clue_script.Commander()

        wsgi.setup_wsgi_server_command(self)

        commander.add(db.LoadDataCommand(self))
        commander.add(shell.ShellCommand(self))

        upgradedb = None
        if self.db_migrations:
            upgradedb = db.UpgradeDBCommand(self)
            commander.add(upgradedb)

        if self.db_metadatas:
            commander.add(db.SyncDBCommand(self, upgradedb))
        if self.initial_data_dir:
            commander.add(db.FreshDBCommand(self))

        if utils.has_rfoo:
            commander.add(shell.RFooShellCommand(self))

        commander.commands['runserver'].rfoo_namespace = \
            commander.commands['shell'].namespace

        return self._commander

    def main(self):
        logging.basicConfig()
        self.logger.setLevel(logging.INFO)
        self.commander.run()


make_manager = ManagerRunner
