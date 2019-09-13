Using koris on OpenStack
========================

Installation
~~~~~~~~~~~~~

Follow the :doc:`installation` instructions to make sure koris is installed properly.

.. _prepare-openstack:

Prepare OpenStack
~~~~~~~~~~~~~~~~~

.. note::

  Doing the below is not strictly required as koris will create a new network
  for you if you don't specify one in the ``config.yml``.

1. In your browser, navigate to the OpenStack project where you wish to deploy the cluster into.
   For this tutorial, the project ``koris-project`` will be used as reference.

2. Download a `OpenStack RC File v3` as ``koris-project-rc.sh`` into the project root.

3. In your project, create or import a key pair via **Compute > Key Pairs** and name it``koris-keys``.

4. Under **Network > Networks**, create a new network including subnet. Change or enter the
   following values (rest stays empty or default):

   ================ ==============
   Parameter        Value
   ================ ==============
   Network Name     koris-network
   Subnet Name      koris-subnet
   Network Address  192.168.0.0/24
   Gateway IP       192.168.0.1
   DNS Name Servers 192.168.0.2
   DNS Name Servers 192.168.0.3
   ================ ==============

5. Under **Network > Routers** create a new router with the name ``koris-router``. Click on the name and
   add a new interface for ``koris-subnet``. Leave the IP address empty as it will be assigned by OpenStack
   automatically. Check **Network > Network Topology** if ``koris-network`` is connected to an external network,
   such as ``ext02`` for example. It should look similar to this:

   .. image:: static/_imgs/os_network.png
         :scale: 75%

6. (**Optional**) If you want a FLoating IP, go to **Network > Floating IPs**. Allocate a new Floating IP to
   the external subnet that is connected with your previously created router.

7. (**Optional**) Koris creates the proper security groups needed for a working cluster. However,
   if you are a building a cluster for a customer which has cloud-connect and needs
   BGP communication, add the correct security rules in OpenStack:

   .. code-block:: shell

     $ neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --remote-ip-prefix <CUSTOMER_CIDR> --direction egress <CLUSTER-SEC-GROUP>
     $ neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --direction ingress --remote-ip-prefix <CUSTOMER_CIDR> <CLUSTER-SEC-GROUP>

Sizing
~~~~~~

The infrastructure requirements depend on the size of your cluster (number of
workers and nodes), as well as the instance type you choose. It's recommended
to have at least three master nodes to ensure high availability. Assuming
you are using three master nodes (``ECS.C1.2-4``) and three worker nodes
(``ECS.UC1.4-4``), your cluster will use the following resources:

============= ===========
Resource type Consumption
============= ===========
CPU           18 cores
Memory        24 GB
Volumes       6
Storage       150 GB
Floating IP   1
Load Balancer 1
============= ===========

.. _usage_deploy_cluster:

Deploy your cluster
~~~~~~~~~~~~~~~~~~~

1. Before you can run ``koris``, source your RC file. Then enter your password:

   .. code-block:: shell

      $ source ~/path/to/your/koris-project-rc.sh
      Please enter your OpenStack Password for project <PROJECT> as user <USER>\:

3. Create a koris configuration file. An example can be found :download:`here <../configs/example-config.yml>`.

4. Pass the your config file to ``koris apply``:

   .. code:: shell

      $ koris apply example-config.yml

   .. note::
        For installing Addons with your initial koris deloyment, please refer to :doc:`addons`.

5. A ``kubectl`` configuration file with the name ``<cluster-name>-admin.conf`` is automatically created
   into your project root. Give you used the default names used in this tutorial it should be
   ``koris-test-admin.conf``. To interact with your cluster you can either pass it with each execution
   such as ``kubectl --kubeconfig`` or export it as an environment variable:

   .. code-block:: shell

      $ export KUBECONFIG=koris-test-admin.conf
      $ kubectl get nodes

Cleanup
~~~~~~~
To completely remove your koris built cluster:

.. code:: shell

      $ koris destroy example-config.yml

Troubleshooting
~~~~~~~~~~~~~~~

In case the cluster fails to boot, you can try and either SSH to the cluster and figure it out yourself.
A quick insight can be gained, without SSH, to what happened at boot time to the cluster.
You can see the output of cloud-init with the following sequence of commands:

.. code-block:: shell

   $ openstack server list
   +--------------------------------------+---------------------------------------+--------+--------------------------------------+-------+-------------+
   | ID                                   | Name                                  | Status | Networks                             | Image | Flavor      |
   +--------------------------------------+---------------------------------------+--------+--------------------------------------+-------+-------------+
   | 3685eec8-494b-4e1c-9c06-dee2068727a5 | node-1-koris-pipe-line-671a519-8034   | ACTIVE | koris-net=10.0.0.9  |       | ECS.C1.4-8  |
   | 402cbc68-b7ad-463f-8657-f553aa263276 | master-2-koris-pipe-line-671a519-8034 | ACTIVE | koris-net=10.0.0.24 |       | ECS.GP1.2-8 |
   | 02752b0a-7f3d-47ac-a509-af9b52e2bf2a | master-3-koris-pipe-line-671a519-8034 | ACTIVE | koris-net=10.0.0.20 |       | ECS.GP1.2-8 |
   | 45ad854a-e484-44f8-bb87-a9e5d0a20b79 | master-1-koris-pipe-line-671a519-8034 | ACTIVE | koris-net=10.0.0.12 |       | ECS.GP1.2-8 |
   | 0c460ba9-4c73-4966-80ec-959f5aaabbe0 | node-2-koris-pipe-line-671a519-8034   | ACTIVE | koris-net=10.0.0.11 |       | ECS.C1.4-8  |
   | 0d4670a3-95b8-4f80-bd92-06b8266b3d6c | node-3-koris-pipe-line-671a519-8034   | ACTIVE | koris-net=10.0.0.8  |       | ECS.C1.4-8  |
   | 611e8b44-f88e-47fe-9ce6-bed168eaea8e | node-1-koris-pipe-line-671a519-8034   | ACTIVE | koris-net=10.0.0.7  |       | ECS.C1.4-8  |
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



