=====
koris
=====

.. image:: https://gitlab.com/noris-network/koris/badges/dev/pipeline.svg
  :target: https://gitlab.com/noris-network/koris/badges/dev/pipeline.svg

.. image:: https://gitlab.com/noris-network/koris/badges/dev/coverage.svg
  :target: https://gitlab.com/noris-network/koris/badges/dev/coverage.svg

.. image:: https://img.shields.io/badge/docs-passed-green.svg
  :target: https://noris-network.gitlab.io/koris/


WARNING: This code is no longer actively maintained! 


Launch kubernetes clusters on OpenStack.


Features
--------

 * Get your kubernetes cluster on noris.cloud in about 5 minutes.
 * Complete provisioning of openstack infrastructure via the installer.
 * Kubernetes 1.14.X supported
 * You can use a pre-built binary installer or the Python sources
 * Resize your cluster as needed (add or remove masters and worker nodes)
 * Multiple plugins already installed (you can add more easily by deploying
   operators):

   - nginx-ingress controller
   - audit logging
   - cloud provider integration (create volumes and loadbalancers from within kubernetes)
   - metrics API enabled

 * Support for two CNI plugins out of the box

   - Calico (default)
   - Flannel

 * (Experimental) Single-Sign-On with:

   - LDAP
   - Gitlab
   - SAML (beta feature)

Quickstart
----------

If you just want to use koris to create a cluster follow the steps below, for more details refer to
:doc:`/installation` and :doc:`/usage`.

If you want to develop, please refer to :doc:`/contributing`.

The complete compiled `documentation of koris can be found here <https://noris-network.gitlab.io/koris>`_.

Prerequisites
^^^^^^^^^^^^^

Install Python 3.6:

.. code:: shell

   sudo apt install python3-pip python3.6-venv

Follow the instructions to install `kubectl`_ .

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

   You can leave your virtual environment by typing ``deactivate``.

3. To install the latest realese (for installation from source see :doc:`/installation`), grab it
   with the following command (replace ``<LATEST_TAG>`` with the latest version tag, for example ``1.2.0``).

   .. code:: shell

     $ pip install -e git+git@gitlab.com:noris-network/koris.git@v<LATEST_TAG>#egg=koris

  Koris is now installed in ``./koris-env/bin`` and usable with an activated virtual environment.

.. note::

   If the machine you would like to install koris on does not have access to
   ``gitlab.com`noris-network download the source distribution on a machine that has,
   and copy it over to your desired machine:

   .. code:: shell

      curl https://gitlab.com/noris-network/koris/-/archive/v<LATEST_TAG>/koris-v<LATEST_TAG>.zip
      scp koris-v<LATEST_TAG>.zip remotehost:~/

   Repeat the steps to create and activate a virtual environment, then install
   the package via ``pip``:

   .. code:: shell

    $ pip install koris-v<LATEST_TAG>.zip

Usage
^^^^^

1. Source your OpenStack RC file and enter your password:

   .. code:: shell

      $ source ~/path/to/your/openstack-openrc.sh
      Please enter your OpenStack Password for project <PROJECT> as user <USER>\:

2. Koris is executed with ``koris <subcommand>``. You can get a list of subcommands
   with ``-h`` or ``--help``.

   .. code:: shell

      $ koris -h
      usage: koris [-h] [--version]
                  [--verbosity {0,1,2,3,4,quiet,error,warning,info,debug}]
                  {add,apply,delete,destroy} ...

      Before any koris command can be run, an OpenStack RC file has to be sourced in
      the shell. See online documentation for more information.

      positional arguments:
        {add,apply,delete,destroy}
                              commands
          add                 Add a worker node or master node to the cluster. Add a
                              node or a master to the current active context in your
                              KUBECONFIG. You can specify any other configuration
                              file by overriding the KUBECONFIG environment
                              variable. If you specify a name and IP address the
                              program will only try to join it to the cluster
                              without trying to create the host in the cloud first.
          apply               Bootstrap a Kubernetes cluster
          delete              Delete a node from the cluster, or the complete
                              cluster.
          destroy             Delete the complete cluster stack

      optional arguments:
        -h, --help            show this help message and exit
        --version             show version and exit
        --verbosity {0,1,2,3,4,quiet,error,warning,info,debug}, -v {0,1,2,3,4,quiet,error,warning,info,debug}
                              set the verbosity level (0 = quiet, 1 = error, 2 =
                              warning, 3 = info, 4 = debug) (default: 3)

3. To get information about each subcommand type:

   .. code:: shell

      $ koris destroy -h
      usage: koris destroy [-h] [--force] config

      positional arguments:
        config

      optional arguments:
        -h, --help   show this help message and exit
        --force, -f

4. Koris creates the proper security groups needed for a working cluster. However,
   if you are a building a cluster for a customer which has cloud-connect and needs
   BGP communication, add correct security rules in OpenStack:

   .. code:: shell

     neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --remote-ip-prefix <CUSTOMER_CIDR> --direction egress <CLUSTER-SEC-GROUP>
     neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --direction ingress --remote-ip-prefix <CUSTOMER_CIDR> <CLUSTER-SEC-GROUP>

5. Create a configuration file. For more information check the :download:`example-config.yml <../configs/example-config.yml>`)
   or refer to the section :ref:`usage_deploy_cluster`.

6. Run ``koris apply`` with your configuration file as the argument:

   .. code:: shell

      $ koris apply your-config.yaml

7. A ``kubectl`` configuration file will be created into your project root with the name of ``<clustername>-admin.conf``.
   You can either pass that with each execution via ``kubectl --kubeconfig=/path/to/koris/your-admin.conf``
   or by exporting it as an environment variable:

   .. code:: shell

       $ export KUBECONFIG=/path/to/koris/your-admin.conf
       $ kubectl get nodes

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
.. _kubectl: https://kubernetes.io/docs/tasks/tools/install-kubectl/

.. highlight:: shell
