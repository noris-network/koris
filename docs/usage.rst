=====
Usage
=====

Pre-requisits
~~~~~~~~~~~~~

1. An OS_RC_FILE v3, you should download it from the openstack WebUI.
2. A pre-created network, and security group.
3. Basic understanding of OpenStack.

Get started
~~~~~~~~~~~
1. Create a local virtual environment for koris (using your favorite tool),
   for example the standard Python has a simple virtual environment tool:

.. code:: shell

   $ mkdir FooBar
   $ cd FooBar && python3 -m venv koris-env

2. Activate the environment with

.. code:: shell

   $ source ./koris-env/bin/activate

3. you are now inside a virtual environment to leave it type `exit`

4. To install koris, use a machine which has access to gitlab.noris.net
   replace <LATEST_TAG> with latest tag, for example 0.5

.. code:: shell

   $ pip3 install https://gitlab.noris.net/PI/koris/-/archive/v<LATEST_TAG>/koris-v<LATEST_TAG>.zip

5. You can now use koris, it is installed in your path under ``./koris-env/bin``.
   If you exist the virtual environment, you need to activate it again as described
   in step 2.

6. Before you can run ``koris`` you need to source your openstack rc file:

.. code:: shell

   $ source ~/path/to/your/openstack-openrc.sh
   Please enter your OpenStack Password for project <PROJECT> as user <USEER>\:

6. To run ``koris`` issue koris <subcommand>. You can get a list of subcommands
   with ``--help``

   .. code:: shell

      $ koris -h
      usage: koris [-h] {certs,destroy,k8s,kubespray,oc} ...

      positional arguments:
        {certs,destroy,k8s,kubespray,oc}
                              commands
          certs               Create cluster certificates
          destroy             Delete the complete cluster stack
          k8s                 Bootstrap a Kubernetes cluster
          ...
      optional arguments:
        -h, --help            show this help message and exit

7. To view the help of each subcommand

   .. code:: shell

      $ koris destroy -h
      usage: koris destroy [-h] config

      positional arguments:
      config

      optional arguments:
      -h, --help  show this help message and exit

.. note::

   If the machine you would like to install koris on does not have access to
   gitlab.noris.net, download the source distribution and copy it over:

   .. code:: shell

      curl https://gitlab.noris.net/PI/koris/-/archive/v<LATEST_TAG>/koris-v<LATEST_TAG>.zip
      scp koris-v<LATEST_TAG>.zip remotehost:~/

   repeat the steps to create and activate a virtual environment, and the install
   the package with pip directly:

   .. code:: shell

      $ pip install koris-v<LATEST_TAG>.zip

8. Koris creates the proper security groups needed for a working cluster. However,
   if you are a building a cluster for a customer which has cloud-connect and needs
   BGP communication add a correct security rule for that.

.. code:: shell

   neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --remote-ip-prefix <CUSTOMER_CIDR> --direction egress <CLUSTER-SEC-GROUP>
   neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --direction ingress --remote-ip-prefix <CUSTOMER_CIDR> <CLUSTER-SEC-GROUP>

9. To create a cluster create a cluster configuration file (see [example](https://gitlab.noris.net/PI/koris/blob/dev/docs/k8s-machines-config.yml).
   Pass this file on the shell to the k8s subcommand

.. code:: shell

   $ koris apply <your-cluster-config.yml>


Troubleshooting
~~~~~~~~~~~~~~~

In case the cluster fails to boot, you can try and either SSH to the cluster and figure it out yourself.
A quick insight can be gained, without SSH, to what happened at boot time to the cluster.
You can see the output of cloud-init with the following sequence of commands:

.. code:: shell

   $ openstack server list
   +--------------------------------------+---------------------------------------+--------+--------------------------------------+-------+-------------+
   | ID                                   | Name                                  | Status | Networks                             | Image | Flavor      |
   +--------------------------------------+---------------------------------------+--------+--------------------------------------+-------+-------------+
   | 3685eec8-494b-4e1c-9c06-dee2068727a5 | node-1-koris-pipe-line-671a519-8034   | ACTIVE | korispipeline-office-net=10.36.18.9  |       | ECS.C1.4-8  |
   | 402cbc68-b7ad-463f-8657-f553aa263276 | master-2-koris-pipe-line-671a519-8034 | ACTIVE | korispipeline-office-net=10.36.18.24 |       | ECS.GP1.2-8 |
   | 02752b0a-7f3d-47ac-a509-af9b52e2bf2a | master-3-koris-pipe-line-671a519-8034 | ACTIVE | korispipeline-office-net=10.36.18.20 |       | ECS.GP1.2-8 |
   | 45ad854a-e484-44f8-bb87-a9e5d0a20b79 | master-1-koris-pipe-line-671a519-8034 | ACTIVE | korispipeline-office-net=10.36.18.12 |       | ECS.GP1.2-8 |
   | 0c460ba9-4c73-4966-80ec-959f5aaabbe0 | node-2-koris-pipe-line-671a519-8034   | ACTIVE | korispipeline-office-net=10.36.18.11 |       | ECS.C1.4-8  |
   | 0d4670a3-95b8-4f80-bd92-06b8266b3d6c | node-3-koris-pipe-line-671a519-8034   | ACTIVE | korispipeline-office-net=10.36.18.8  |       | ECS.C1.4-8  |
   | 611e8b44-f88e-47fe-9ce6-bed168eaea8e | node-1-koris-pipe-line-671a519-8034   | ACTIVE | korispipeline-office-net=10.36.18.7  |       | ECS.C1.4-8  |
   +--------------------------------------+---------------------------------------+--------+--------------------------------------+-------+-------------+

   $  $ openstack console log show 3685eec8-494b-4e1c-9c06-dee2068727a5

   [    0.000000] Initializing cgroup subsys cpuset
   [    0.000000] Initializing cgroup subsys cpu
   ... snipped ...
   [   22.671075] cloud-init[1478]: Reading state information...
   [   22.680297] cloud-init[1478]: Del docker-ce 17.12.1~ce-0~ubuntu [30.2 MB]
   [   23.572631] cloud-init[1478]: mkdir: created directory '/var/lib/kubernetes/'
   [   23.587803] cloud-init[1478]: Failed to execute operation: File exists


This indicates that the cloud-init script failed to run, hence the nodes didn't join the cluster.


