.. highlight:: shell

============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs via  `Gitlab issues`_ .

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the Gitlab issues for features. Anything tagged with "enhancement"
and "help wanted" is open to whoever wants to implement it.

Write Documentation
~~~~~~~~~~~~~~~~~~~

Koris could always use more documentation, whether as part of the
official koris docs, in docstrings, or even on the web in blog posts,
articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to get in touch is via `Gitlab issues`_.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

.. _get_started_contributing:

Start contributing
------------------

Ready to contribute? Here's how to set up `koris` for local development.

1. Fork the `koris` repo on Gitlab.
2. Clone your fork locally::

    $ git clone git@gitlab.com:noris-network/koris.git

3. Install your local copy into a virtualenv.
   This is how you set up your fork for local development::

    $ cd koris/
    $ python3 -m venv myenv
    $ source myenv/bin/activate
    $ pip3 install -r requirements_dev.txt

If you prefer to use `Pipenv` you can let Pipenv manage the virtual environment::

    $ cd koris
    $ pipenv --python 3.6
    $ pipenv install --dev

.. note::

   If you are familiar with more modern python development tools like
   ``pipenv``, you can also use pipenv (we have a ``Pipenv`` file in the repository).

   see how we manage our dependencies_.

4. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

5. When you're done making changes, check that your changes pass flake8 and the
   tests, including testing other Python versions with tox::

    $ make lint
    $ make test

   To get flake8 and tox, just pip install them into your virtualenv.

6. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit
    $ git push origin name-of-your-bugfix-or-feature

7. Submit a merge request through the Gitlab website.

Merge Request Guidelines
------------------------

Before you submit a merge request, check that it meets these guidelines:

1. The merge request should include tests.
2. If the merge request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.
3. The merge request should support Python3.6 and newer versions only. Check
   and make sure that the tests pass for all supported Python versions.

.. _dependencies:

How we manage koris's dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Python loads modules and packages which are not in the standard library
from a directory called ``site-packages`` (on Debian based systems
``dist-packages``).
Usually, this directory is in ``/usr/lib/python3.X/site-packages/`` which is not
writable for normal users. Also this directory will contain system important
packages. Hence, the Python community adopted a solution called
``virtual-environments``. These are directories with hard-links to the python
interpreter and a set of scripts to change the environment variables such that
Python loads modules and packages from a new location e.g.
``my-virtualenv/lib/python3.X/site-packages``. A virtual environment also has
it's binaries installed in ``my-virtualenv/bin`` hence ``pip3`` and other
python scripts will be found there.
The standard library of ``Python3.X`` already contains a module to create virtual
environments. These can be created with::

   $ python3 -m venv <path-to-the-new-env>

This environment can be activated with::

   $ cd <path-to-the-new-env>
   $ source ./bin/activate

Now one can installs packages in the new environment using the new environment
``pip`` installer::

   $ which pip3
   <path-to-the-new-env>/bin/pip3

Using ``pip3`` in a virtual environment still requires one to document which
packages are needed for a certain Python software to work. By convention
these dependencies are documented in ``requirements.txt``. This file contains
everything needed to run the software after installation. By convention also,
there are one or more files documenting extra dependencies for development and
testing. These are called ``requirements_dev.txt`` or ``requirements_test.txt``.
These files include the dependencies from ``requirements.txt`` using the
directive ``-r requirements.txt``.
The file ``requirements.txt`` is used by ``setup.py`` and many python project
write code in ``setup.py`` to read the file when invoking
``python setup.py install``. However, this project has a pretty minimal
``setup.py`` which only uses PBR_. ``PBR_`` is a great tool for building software
project, and upon invocation it will automatically read ``requirements.txt``.
Therefore, you don't need to modify ``setup.py`` to include the dependencies
at installation time. See below how we keep ``requirements.txt`` updated.

In order to ease the work flow of developers who need to manage multiple
development environments, the python community has come with a few solutions.
They where all more or less working, but not perfect. Recently, a new contender,
entered the ring. This tool, ``pipenv`` aims not only to manage virtual
environments but also to manage the dependencies documented in
``requirements.txt``. ``pipenv`` uses two files, ``Pipfile`` and ``Pipfile.lock``.
When you install a new package needed for ``koris`` this package will be recorded
in ``Pipfile``.
Usually, you don't want to change neither of this files. ``pipenv`` has built-in
tools to help updating the dependencies and documenting changes in
``requirements.txt``.

Keeping requirements.txt updated
++++++++++++++++++++++++++++++++

With every minor release of ``koris`` (X.Y, but not X.Y.Z) we will check that
all the dependencies are the latest, such that we won't have software rot, or
older packages with CVEs in our dependencies. This is done with::

   $ pipenv lock -r | cut -d" " -f 1 > requirements.txt

If all tests pass (including integration tests) we update ``requirements.txt``
by committing the changes.

Git collaborations guide lines
++++++++++++++++++++++++++++++

1. Never `(ever ever ever)**10` use::

   $ git commit -a

Instead make small commits that are easy to reason about and to understand.

2. Never `(ever ever ever)**10` use::

   $ git commit -m "I made some change"

Instead write a `nice commit message`_ with a short title and informative body.
Make sure the body contains a reference to the ticket you are working on.
The reference should be in the form of a the Gitlab issue number.
Make sure your titles are meaningful, they will appear in the ChangeLog!

.. _nice commit message: https://code.likeagirl.io/useful-tips-for-writing-better-git-commit-messages-808770609503

Run a single test
+++++++++++++++++

To run a subset of tests::

$ py.test tests.test_koris

Developer helper utils - Makefile
+++++++++++++++++++++++++++++++++

The repository contains an extensive ``Makefile`` which is mainly for helping you
develop faster. Issue ``make help`` to see all th available functions.

To run the complete integration test from your local machine issue::

   $ make integration-test KEY=your-key

You can run make tragets with::

   $ make clean-after-integration-test REV=HEAD~1


Continous Integration
+++++++++++++++++++++

With every ``git push`` a complete test suite is running in `Gitlab CI`_.
This test suite builds a complete Kubernetes cluster in noris.cloud. To access
the resources of this cluster you need an OpenStack account in noris.cloud, and
your user has to be added to the project ``korispipeline``.
Make sure you have your user added to the project, talk to the OpenStack team.

.. _Gitlab issues: https://gitlab.com/noris-network/koris/issues
.. _PBR: https://docs.openstack.org/pbr/latest/
.. _Gitlab CI: https://gitlab.com/noris-network/koris/pipelines
