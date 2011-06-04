from clue_script import Command
import sys
import os
import code

prog_prefix = os.path.basename(sys.argv[0])

banner = '''\
Python %s on %s
Type "help" for more information.

dir() =>
    registry  - the active Pyramid registry
    root      - the traversal root
    app       - the active wsgi application
''' % (sys.version, sys.platform)


class _ShellCommand(Command):
    namespace = {}
    banner = banner

    def __init__(self, manager):
        self.manager = manager
        self.logger = manager.logger

    def run(self, argv):
        prog = prog_prefix + ' ' + self.__name__
        parser = self.manager._argparser_factory(prog=prog,
                                                 description=self.__doc__)
        parser.parse_args(argv)

        self.interact(self.banner, local=self.namespace)


class ShellCommand(_ShellCommand):
    '''Launch a Python shell
    '''

    __name__ = 'shell'

    interact = staticmethod(code.interact)

    @property
    def namespace(self):
        if hasattr(self, '_namespace'):
            return self._namespace

        from pyramid.scripting import get_root

        innerapp = self.get_app_with_registry(self.manager.app)
        root, closer = get_root(innerapp)
        self._namespace = {'root': root,
                           'registry': innerapp.registry,
                           'app': self.manager.app}
        return self._namespace

    def get_app_with_registry(self, app, count=0):
        if count > 10:
            return None

        if hasattr(app, 'registry'):
            return app
        elif hasattr(app, 'app'):
            return self.get_app_with_registry(app.app, count + 1)
        elif hasattr(app, 'application'):
            return self.get_app_with_registry(app.application, count + 1)


class RFooShellCommand(_ShellCommand):
    '''Launch a remote Python shell that connects to the running server
    '''

    __name__ = 'rshell'

    def interact(self, banner, local=None):
        import rfoo.utils.rconsole
        rfoo.utils.rconsole.interact(banner)
