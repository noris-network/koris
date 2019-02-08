.. highlight:: shell

============
Installation
============

This page focuses on how to install koris for regular usage. If you want to install
koris for development, please refer to :ref:`get_started_contributing`.

From stable release
-------------------

To install koris, first download the source package:

.. code::

   https://gitlab.noris.net/PI/koris/-/archive/v0.6.3/koris-v0.6.3.zip

Replace ``0.6.3`` with the latest release tag.

Create a virtual environment:

.. code-block:: shell

    $ python3 -m venv korisenv
    $ source korisenv/bin/activate
    (korisenv) $ pip3 install koris-0.6.3.tar.gz
    Processing ./koris-0.6.3.dev88.tar.gz
    Collecting adal==1.1.0 (from koris==0.6.3.dev88)
    Using cached https://files.pythonhosted.org/packages/15/2b/8f674c2a20bb2a55f8f1c8fb7a458c9b513409b2cfc42f73e4cbc1ee757e/adal-1.1.0-py2.py3-none-any.whl
    Collecting appdirs==1.4.3 (from koris==0.6.3.dev88)
    Using cached https://files.pythonhosted.org/packages/56/eb/810e700ed1349edde4cbdc1b2a21e28cdf115f9faf263f6bbf8447c1abf3/appdirs-1.4.3-py2.py3-none-any.whl
    Collecting asn1crypto==0.24.0 (from koris==0.6.3.dev88)
    ...

If you don't have `pip`_ installed, this `Python installation guide`_ can guide
you through the process.

.. _pip: https://pip.pypa.io
.. _Python installation guide: http://docs.python-guide.org/en/latest/starting/installation/


From source
------------

Clone the `Gitlab repo`_:

.. code-block:: shell

    $ git clone git@gitlab.noris.net:PI/koris.git
    $ cd koris

Create and activate a virtual environment:

.. code-block:: shell

    $ python3 -m venv korisenv
    $ source korisenv/bin/activate

Install the requirements:

.. code-block:: shell

    $ pip install -r requirements.txt
    $ python setup.py install

Refer to :doc:`usage` for instructions on how to use koris.

.. _Gitlab repo: https://gitlab.noris.net/PI/koris/
