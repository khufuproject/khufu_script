import clue_script
from weberror.evalexception import make_eval_exception
from weberror.errormiddleware import make_error_middleware
from weberror.errormiddleware import formatter

from .utils import maybe_resolve


class Reporter(object):
    def __init__(self, manager):
        self.manager = manager

    def report(self, exc_info):
        m = '\n'.join(formatter.format_text(exc_info))
        self.logger.error(m)


def _app_factory(manager):
    settings = manager.settings
    global_conf = {}
    app_factory = maybe_resolve(manager.app_factory)
    app = app_factory(global_conf, **settings)
    if settings.get('DEBUG', False):
        app = make_eval_exception(app, global_conf,
                                  reporters=[Reporter(manager)])
    else:
        app = make_error_middleware(app, global_conf)

    return app


def setup_wsgi_server_command(manager):
    runserver = clue_script.make_reloadable_server_command(
        lambda manager=manager: _app_factory(manager))
    runserver.parser.set_defaults(with_reloader=True)
    manager.commander.add(runserver)
    return runserver
