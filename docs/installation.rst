.. highlight:: shell

============
Installation
============

Stable release
--------------

To install koris, first download the source package from the tags page in gitlab:

.. code::

   https://gitlab.noris.net/PI/koris/-/jobs/artifacts/v0.7.2/download?job=build

Replace 0.7.2 with the latest tag. This will download a file called
``artifacts.zip``.

run the following commands in your terminal:

.. code-block:: console

    $ otiram@yoni:~/Software/tmp $ python3 -m venv korisenv
    otiram@yoni:~/Software/tmp $ source korisenv/bin/activate
    otiram@yoni:~/Software/tmp |korisenv| $ cp  artifacts.zip .
    otiram@yoni:~/Software/tmp |korisenv| $ unzip artifacts.zip
    Archive:  artifacts.zip
    creating: dist/
    inflating: dist/koris-0.7.2.tar.gz
    otiram@yoni:~/Software/tmp |korisenv| $ pip install dist/koris-0.7.2.tar.gz
    Processing ./dist/koris-0.7.2.tar.gz
    Requirement already satisfied: adal==1.1.0 in /home/otiram/.local/share/virtualenvs/koris-ijrmZRy0/lib/python3.6/site-packages (from koris==0.7.2) (1.1.0)
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
