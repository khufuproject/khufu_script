============
khufu_script
============

Overview
========

*khufu_script* provides a *manage script* for Khufu/Pyramid projects.
Following the usual **Khufu** opinions, certain commands assume
you are using SQLAlchemy to manage your data.

Usage
=====

Using *khufu_script* is as easy defining the runner and registering it
with disutils console_script entry point.

As an example, consider a Pyramid-based web app with a distribution name
of "NoteTaker" and a main package of "notetaker".

First create ``notetaker/manage.py`` with the following content::

  import khufu_script
  settings = {
      'sqlalchemy.url': 'sqlite:///notetaker.db'
  }
  main = khufu_script.make_manager(name='NoteTaker',
                                   app_factory='notetaker.app',
                                   config_filename='notetaker-settings.ini',
                                   settings=settings,
                                   db_metadatas=['notetaker.models.Base.metadata']).main
  if __name__ == '__main__':
      main()

Next make adjustments to ``setup.py``::

  from setuptools import setup

  setup(name='NoteTaker',
        # ...
        entry_points={
          'console_scripts': [
              'notetaker-manage = notetaker.manage:main',
              ]
          }
        )

After installing your app you can launch your app by typing::

  $ notetaker-manage

Or by running the module directly::

  $ python -m notetaker.manage

Available Commands
==================

::

  Commands:
      runserver             Run a reloadable development web server.
      loaddata              Add data based on the YAML from filename
      shell                 Launch a Python shell
      syncdb                Ensure all database tables exist

Credits
=======

Created and maintained by Rocky Burt <rocky AT serverzen DOT com>.
