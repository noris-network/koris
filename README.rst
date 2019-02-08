=====
koris
=====

.. image:: https://gitlab.noris.net/PI/koris/badges/dev/pipeline.svg
  :target: https://gitlab.noris.net/PI/koris/badges/dev/pipeline.svg

.. image:: https://gitlab.noris.net/PI/koris/badges/dev/coverage.svg
  :target: https://gitlab.noris.net/PI/koris/badges/dev/coverage.svg

.. image:: https://img.shields.io/badge/docs-passed-green.svg
  :target: https://pi.docs.noris.net/koris/


Launch kubernetes clusters on OpenStack.


Features
--------

* Get your kubernetes cluster on noris.cloud in about 5 minutes.

Demo:

.. image:: https://gitlab.noris.net/PI/koris/raw/dev/docs/static/_imgs/kolt-demo.gif
   :target: https://gitlab.noris.net/PI/koris/raw/dev/docs/static/_imgs/kolt-demo.gif
   :scale: 12%

Quickstart
----------

If you just want to use koris to create a cluster follow the steps below, for more details refer to
:doc:`/installation` and :doc:`/usage`.

If you want to develop, please refer to :doc:`/contributing`.

The complete compiled `documentation of koris can be found here <https://pi.docs.noris.net/koris/>`_.

Prerequisites
^^^^^^^^^^^^^

1. Make sure you are on a machine that has access to `gitlab.noris.net <https://gitlab.noris.net/>`_.

2. Have Python3.6 installed.

3. Via the OpenStack web UI, download an ``OS_RC_FILE v3`` file for the project you want to deploy
   your cluster into.

Installation
^^^^^^^^^^^^

1. Create a local virtual environment for koris (using your favorite tool).
   For example the standard Python has a simple virtual environment tool:

   .. code:: shell

     $ mkdir koris
     $ cd koris && python3 -m venv koris-env

2. Activate the environment with:

   .. code:: shell

     $ source koris-env/bin/activate

   You can leave your virtual environment by typing ``exit``.

4. Grab the latest release with the following command (replace 
   ``<LATEST_TAG>`` with the latest version tag, for example ``0.9.0``.

   .. code:: shell

     $ pip install -e git+git@gitlab.noris.net:PI/koris.git@v<LATEST_TAG>#egg=koris

  Koris is now installed in ``./koris-env/bin`` and usable with an activated virtual environment.

.. note::

   If the machine you would like to install koris on does not have access to
   ``gitlab.noris.net``, download the source distribution on a machine that has,
   and copy it over to your desired machine:

   .. code:: shell

      curl https://gitlab.noris.net/PI/koris/-/archive/v<LATEST_TAG>/koris-v<LATEST_TAG>.zip
      scp koris-v<LATEST_TAG>.zip remotehost:~/

   Repeat the steps to create and activate a virtual environment, then install
   the package via ``pip``:

   .. code:: shell

    $ pip install koris-v<LATEST_TAG>.zip

5. Source your OpenStack RC file and enter your password:

   .. code:: shell

      $ source ~/path/to/your/openstack-openrc.sh
      Please enter your OpenStack Password for project <PROJECT> as user <USEER>\:

6. Koris is executed with ``koris <subcommand>``. You can get a list of subcommands
   with ``-h`` or ``--help``.

   .. code:: shell
   
      $ koris -h
      usage: koris [-h] [--version] {add,apply,destroy} ...

      positional arguments:
        {add,apply,destroy}  commands
          add                Add a worker node or master node to the cluster. Add a
                            node to the current active context in your KUBECONFIG.
                            You can specify any other configuration file by
                            overriding the KUBECONFIG environment variable.
          apply              Bootstrap a Kubernetes cluster
          destroy            Delete the complete cluster stack

      optional arguments:
        -h, --help           show this help message and exit
        --version            show version and exit

7. To view the help of each subcommand type:

   .. code:: shell

      $ koris destroy -h
      usage: koris destroy [-h] [--force] config

      positional arguments:
        config

      optional arguments:
        -h, --help   show this help message and exit
        --force, -f

8. Koris creates the proper security groups needed for a working cluster. However,
   if you are a building a cluster for a customer which has cloud-connect and needs
   BGP communication, add correct security rules in OpenStack:

   .. code:: shell

     neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --remote-ip-prefix <CUSTOMER_CIDR> --direction egress <CLUSTER-SEC-GROUP>
     neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --direction ingress --remote-ip-prefix <CUSTOMER_CIDR> <CLUSTER-SEC-GROUP>

9. Create a configuration file (see `example <https://gitlab.noris.net/PI/koris/blob/dev/docs/example-config.yml>`_).

10. Run ``koris apply`` with your configuration file as the argument:

   .. code:: shell

      $ koris apply your-config.yaml

11. A ``kubectl`` configuration file will be created into your project root with the name of 
   ``<clustername>-admin.conf``. You can either pass that with each execution via
   ``kubectl --kubeconfig=/path/to/koris/your-admin.conf`` or by exporting it as an environment variable:

   .. code:: shell

       $ export KUBECONFIG=/path/to/koris/your-admin.conf
       $ kubectl get nodes

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage

.. highlight:: shell
