Resizing your cluster
=====================

If you deployed koris in OpenStack, you can add worker nodes and remove worker nodes
as your workloads change.

Adding worker nodes
~~~~~~~~~~~~~~~~~~~

Adding worker nodes is easy as this:

.. code:: shell

   $ kubectl get nodes
   NAME          STATUS     ROLES    AGE     VERSION
   master-1-am   Ready      master   8m59s   v1.12.7
   node-1-am     Ready      <none>   7m14s   v1.12.7

Here we have a cluster with 1 worker node and 1 master node. Now we add a worker
nodes:

.. code:: shell

   $ koris add --amount 2 --zone de-nbg6-1a --flavor ECS.UC1.4-4 add-m.yml
   [!] The network [koris-net] already exists. Skipping
   [!] subnetwork [koris-subnet] already exists. Skipping...
   [!] The router [koris-router] already exists. Skipping
   [!] Gathering node information from OpenStack ...
   created volume <Volume: 899b5d15-41dc-47b0-9deb-2e5911f2bbd5> BSS-Performance-Storage
   Creating instance node-2-am...
   waiting for 5 seconds for the machine to be launched ...
   created volume <Volume: 6d84d571-6820-4552-9896-2da15ca6e4fb> BSS-Performance-Storage
   Creating instance node-3-am...
   waiting for 5 seconds for the machine to be launched ...
   Instance: node-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-3-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-3-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-3-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-3-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-3-am is in in BUILD state, sleeping for 5 more seconds
   Instance: node-2-am is in ACTIVE state
   Instance booted! Name: node-2-am, IP: ACTIVE, Status : 10.0.0.56
   Instance: node-3-am is in ACTIVE state
   Instance booted! Name: node-3-am, IP: ACTIVE, Status : 10.0.0.119
   [!] An updated cluster configuration was written to: add-m.updated.yml

The machines will now boot in OpenStack, and join the cluster. Notice that,
an updated configuration file was written to the disk. It contains an update
number of worker nodes.

Here we used `koris add` without the role. The flag `--role` defaults to node.
You can also use the command in the following way:

.. code::

   koris add --role node --amount 2 --zone de-nbg6-1a --flavor ECS.UC1.4-4 add-m.yml

.. code:: shell

   $ diff add-m.yml add-m.updated.yml  | grep nodes
   < n-nodes: 1
   > n-nodes: 3

The boot and join process can take a few moments. It is possible to track the
logs of the booting machine with openstack, without needed to SSH to the machine.

.. code:: shell

   $  openstack console log show node-2-a

Finally, the new worker nodes have joined the cluster:

.. code:: shell

   $ kubectl get nodes
   NAME          STATUS     ROLES    AGE   VERSION
   master-1-am   Ready      master   19m   v1.12.7
   node-1-am     Ready      <none>   18m   v1.12.5
   node-2-am     NotReady   <none>   89s   v1.12.7
   node-3-am     NotReady   <none>   87s   v1.12.7


Notice that, kubernetes can tolerate different versions in the cluster.
We use this to update the claster in the manner of replacing old nodes
with new ones.

.. _add_master_nodes:

Adding master nodes
~~~~~~~~~~~~~~~~~~~

Adding master nodes is easy too:

.. code:: shell

   $ koris add --role master --zone de-nbg6-1a --flavor ECS.GP1.2-8 add-m.yml
   [!] The network [koris-net] already exists. Skipping
   [!] subnetwork [koris-subnet] already exists. Skipping...
   [!] The router [koris-subnet] already exists. Skipping
   [!] Gathering control plane information from OpenStack ...
   created volume <Volume: e717ee52-9291-4fc4-9fe7-dcff1a38af76> BSS-Performance-Storage
   Creating instance master-2-am...
   waiting for 5 seconds for the machine to be launched ...
   Instance: master-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: master-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: master-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: master-2-am is in ACTIVE state
   Instance booted! Name: master-2-am, IP: ACTIVE, Status : 10.0.0.100
   [!] An updated cluster configuration was written to: add-m.updated.yml
   deployment.apps/master-adder unchanged
   Waiting for the pod to run ...
   Extract current etcd cluster state...
   Current etcd cluster state is: master-1-am=https://10.0.0.27:2380
   Executing adder script on current master node...
   ... snipped ...
   [markmaster] Marking the node master-2-am as master by adding the label "node-role.kubernetes.io/master=''"
   [markmaster] Marking the node master-2-am as master by adding the taints [node-role.kubernetes.io/master:NoSchedule]

As soon as the execution is done, you will be able to see the new master node
in the cluster:

.. code:: shell

   $ kubectl get nodes
   NAME          STATUS     ROLES    AGE   VERSION
   master-1-am   Ready      master   27m   v1.12.7
   master-2-am   NotReady   master   11s   v1.12.7
   node-1-am     Ready      <none>   26m   v1.12.5
   node-2-am     Ready      <none>   10m   v1.12.7
   node-3-am     Ready      <none>   10m   v1.12.7

A couple of minutes later, the new master will become ready:

.. code:: shell

   $ kubectl get nodes
   NAME          STATUS   ROLES    AGE     VERSION
   master-1-am   Ready    master   29m     v1.12.7
   master-2-am   Ready    master   2m12s   v1.12.7
   node-1-am     Ready    <none>   28m     v1.12.5
   node-2-am     Ready    <none>   12m     v1.12.7
   node-3-am     Ready    <none>   12m     v1.12.7

.. note::

   In the current version of koris, the **add-master feature does not work with** :ref:`dex_docs`. This means that if you adding
   additional masters with a config that contains a Dex configuration block, the kube-apiserver pod launched on the new
   master will not be properly configured to use Dex and may even fail to launch.

What happens under the hood
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When we add a worker node or a master node the following happens:

 1. A bootstrap token is created in Kuberenetes.
 2. This bootstrap token is fetched and injected into a cloud-init script, which
    also includes all the information required for a node to join the cluster.
 3. An instance in OpenStack is created with that cloud-init script.
 4. Once the instance has completed the boot process, cloud-init will run and
    call ``kubeadm join`` with the cluster information and the bootstrap token.
 5. Kuberenetes authorizes the token, delivers the required information needed
    to perform the node bootstrap.
 6. The node become part of the cluster.

Deleting nodes
~~~~~~~~~~~~~~

Master and worker nodes can be deleted via  the command ``koris delete node``,
which requires the ``--name`` flag to be passed:

.. code:: shell

   $ koris delete node --name master-1-am add-m.updated.yml

This command will perform the following:

1. `Drain <https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/>`_
    the node of all workloads.

2.  If the node is a master, remove it from the etcd cluster.

3. Delete the node from Kubernetes.

4. Delete the node from OpenStack.

5. If deletiong from OpenStack was successful, an updated config file will be
   saved alongside the original.
