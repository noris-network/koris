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
   [!] The network [k8s-nude] already exists. Skipping
   [!] subnetwork [NORIS-NUDE-OS-K8S-DEV-SUBNET] already exists. Skipping...
   [!] The router [NORIS-K8S-NUDE-OS-MGMT-ROUTER] already exists. Skipping
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
   Instance booted! Name: node-2-am, IP: ACTIVE, Status : 10.32.192.56
   Instance: node-3-am is in ACTIVE state
   Instance booted! Name: node-3-am, IP: ACTIVE, Status : 10.32.192.119
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

Adding master nodes
~~~~~~~~~~~~~~~~~~~

Adding master nodes is easy too:

.. code:: shell

   $ koris add --role master --zone de-nbg6-1a --flavor ECS.GP1.2-8 add-m.yml
   [!] The network [k8s-nude] already exists. Skipping
   [!] subnetwork [NORIS-NUDE-OS-K8S-DEV-SUBNET] already exists. Skipping...
   [!] The router [NORIS-K8S-NUDE-OS-MGMT-ROUTER] already exists. Skipping
   [!] Gathering control plane information from OpenStack ...
   created volume <Volume: e717ee52-9291-4fc4-9fe7-dcff1a38af76> BSS-Performance-Storage
   Creating instance master-2-am...
   waiting for 5 seconds for the machine to be launched ...
   Instance: master-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: master-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: master-2-am is in in BUILD state, sleeping for 5 more seconds
   Instance: master-2-am is in ACTIVE state
   Instance booted! Name: master-2-am, IP: ACTIVE, Status : 10.32.192.100
   [!] An updated cluster configuration was written to: add-m.updated.yml
   deployment.apps/master-adder unchanged
   Waiting for the pod to run ...
   Extract current etcd cluster state...
   Current etcd cluster state is: master-1-am=https://10.32.192.27:2380
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

What happens under the hood
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Although one subcommand `add` is used for adding masters and nodes, under the
hood, adding master and worker nodes take very different code paths.

When we add a worker node the following happens:

 1. A bootstrap token is created in Kuberenetes.
 2. This bootstrap token is fetched and injected into a cloud-init script, which
    also includes all the information required for a node to join the cluster.
 3. An instance in OpenStack is created with that cloud-init script.
 4. Once the instance has completed the boot process, cloud-init will run and
    call ``kubeadm join`` with the cluster information and the bootstrap token.
 5. Kuberenetes authorizes the token, delivers the required information needed
    to perform the node bootstrap.
 6. The node become part of the cluster.


When we add a master node the following happens:

 1. A deployment with a single pod (*master-adder*) responsible for the master bootstrap is created.
    This happens only once.
 2. An instance is created in OpenStack. It gets provisioned with  a very minimal
    cloud-init script and has no knowledge of the cluster.
 3. Etcd gets queried in order to retrieve all etcd master members. This output is
     formatted, as it's required for adding the new master to the etcd cluster.
 4. The *master-adder* pod will launch with all required information to join
    a new master tothe  cluster. This information includes an SSH key allowing to
    connect to the new instance, certificates and keys required to add a new
    Kubernetes master, as well as certificates and keys required to create a new etcd
    member.
 5. Once the instance is running in OpenStack, the *master-adder* pod will SSH
    into the new instance and perform a series of commands to create a new master and
    add a new member to the etcd cluster.

    This is done by:
     * Copying all the keys and certificates using sftp (and other
         configuration files if needed).
     * Creating a configuration file for ``kubeadm``
     * Calling all necessary commands of ``kubeadm`` explicitily up until the instance needs
        to join the etcd cluster.
     * Adding the instance as a new member to the exisiting etcd cluster.
     * Continuing with all the other steps need to complete ``kubeadm init``.
