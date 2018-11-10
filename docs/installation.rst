.. highlight:: shell

============
Installation
============


Stable release
--------------

To install koris, first download the source package form:

.. code::

   https://gitlab.noris.net/PI/koris/-/archive/v0.6.3/koris-v0.6.3.zip

Replace 0.6.3 with the latest tag.

run this command in your terminal:

.. code-block:: console

    $ otiram@yoni:~/Software/tmp $ python3 -m venv korisenv
    otiram@yoni:~/Software/tmp $ source korisenv/bin/activate
    otiram@yoni:~/Software/tmp |korisenv| $ pip3 install koris-0.6.3.tar.gz
    Processing ./koris-0.6.3.dev88.tar.gz
    Collecting adal==1.1.0 (from koris==0.6.3.dev88)
    Using cached https://files.pythonhosted.org/packages/15/2b/8f674c2a20bb2a55f8f1c8fb7a458c9b513409b2cfc42f73e4cbc1ee757e/adal-1.1.0-py2.py3-none-any.whl
    Collecting appdirs==1.4.3 (from koris==0.6.3.dev88)
    Using cached https://files.pythonhosted.org/packages/56/eb/810e700ed1349edde4cbdc1b2a21e28cdf115f9faf263f6bbf8447c1abf3/appdirs-1.4.3-py2.py3-none-any.whl
    Collecting asn1crypto==0.24.0 (from koris==0.6.3.dev88)
    ...

 This is the preferred method to install kolt, as it will always install the most recent stable release.

If you don't have `pip`_ installed, this `Python installation guide`_ can guide
you through the process.

.. _pip: https://pip.pypa.io
.. _Python installation guide: http://docs.python-guide.org/en/latest/starting/installation/


From sources
------------

The sources for colt can be downloaded from the `Github repo`_.

You can either clone the public repository:

.. code-block:: console

    $ git clone git://gitlab.noris.net:PI/kolt.git

Once you have a copy of the source, you can install it with:

.. code-block:: console

    $ pip3 install -r requirements.txt
    $ python3 setup.py install

.. _Github repo: https://gitlab.noris.net/PI/kolt/
