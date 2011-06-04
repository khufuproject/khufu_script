import sys
import os
import code

prog_prefix = os.path.basename(sys.argv[0])


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

        prog = prog_prefix + ' ' + self.__name__
        parser = self.manager._argparser_factory(prog=prog,
                                                 description=self.__doc__)
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
