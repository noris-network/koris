Software architecture
---------------------

This document lays out the basics of koris' software architecture.
koris is written in Python and bash, to work on the project you need
basic understanding of both programming language, plus an understanding
of OpenStack and Kubernetes.

Koris uses Python to communicate with the OpenStack API to provision
virtual machines and to configure a loadbalancer to serve HTTP request
to the Kubernetes API.

When you run ``koris apply <config.yaml>`` the configuration file is
parsed and the following actions will be taken:

1. Query openstack for the kubernetes cluster status, and openstack resources
   status. These include: security group existence and rules, volumes, machines
   and loadbalancer.

2. Creation of volumes based on pre-created images which already contain the
   software packages needed to bootstrap a kubernetes cluster.

3. Creation of virtual network interfaces.

4. Create a set of virtual machines with attached volume and network interface 
   previously created. This first set of machines (1 or more) are the kubernetes
   masters.

5. Create a loadbalancer and add the first master to the loadbalancer listener
   members.

6. The first master will boot with a special cloud-init served via the Openstack
   API and will configure a single master of kubernetes with and etcd static pod.
   This master has an SSH key which can access the other master.
   When these masters will have SSH up and running, the bootstrap script
   will execute a set of commands on them. This commmand will configure the kubernetes
   control plane components to run on them and and extend the etcd cluster by 
   adding cluster members.

7. Create a set of virtual machines that will become kubernetes worker nodes.
   These machines will boot with a volume and network interfaces pre-configured earlier.
   These machines will receive a cloud-init script which will supply the information
   needed for joining the kubernetes cluster in a secure way.

8. When all the control plane machines are booted, the loadbalancer balancer is
   reconfigured again, and all the masters are added to the loadbalancer's listener.

Steps 4 and 7 actually happen in parallel, since these steps are not dependent on each
other. The nodes will wait for the kubernetes cluster API to become available if they
complete the boot sequence first.

The ``kolt`` source code is devided into modules and packages responsible for the steps
above.

The main driver of the steps describe above is in ``kolt.cloud.builder`` which abstracts
the dirty details of communication with the OpenStack API, which is found in
``kolt.cloud.openstack``.

The package ``koris.provision`` includes a python module ``cloud_init`` responsible of
preparing the cloud-init file (also known as ``userdata``) for each machine type.
The directory ``koris.provision.userdata`` contains all the BASH shell scripts for each
machine type. These shell scripts can be used to provision bare metal
clusters with minimal effort too. 

The module ``koris.ssl`` is responsible of creating SSL keys and certificates used by
``kubeadm`` for creating the etcd cluster and kubernetes cluster which uses it for its
storage backend. The modules is also used to create SSH key infrastructure use by the
cluster first master to SSH into the other masters.

The packages ``koris.util`` contains general purpose code to handle exceptions, logging
and coloring output.
