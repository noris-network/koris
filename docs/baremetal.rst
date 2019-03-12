Using koris on bare metal
=========================

This is a short guide which is intended if you intend to install koris on Bare
Metal machine or Virtual Machines which do not use the official koris image.

First you need to make sure you can SSH to all the machines and you have a loadbalancer
configured with a domain name.

Start with configuring the load balancer listener group to have 1 member pointing
to you master. You need to direct traffic from coming to your domain on port 6443
to port 6443 of the first master's IP address.

Then you need to write a ``koris.env`` file and copy it to the first master
in ``/etc/kubernetes/koris.env``

.. code: shell

   export BOOTSTRAP_NODES=1
   export POD_SUBNET="10.233.0.0/16"
   export POD_NETWORK="CALICO"
   export LOAD_BALANCER_PORT="6443"
   export MASTERS_IPS=( 10.36.23.29 10.36.23.4 10.36.23.37 )
   export MASTERS=( bare-metal-master-1 bare-metal-master-2 bare-metal-master-3 )
   export LOAD_BALANCER_IP=10.36.23.11
   #export LOAD_BALANCER_DNS
   export BOOTSTRAP_TOKEN=e8e199.9c4a416087c3af19
   export OPENSTACK=0
   export SSH_USER=ubuntu
   export K8SNODES=( node-1 node-2 node-3 .... )


==================    ==========================================================
Parameter             Explanation
==================    ==========================================================
BOOTSTRAP_NODES       install kubernetes componetes on the nodes and master if 1
POD_SUBNET            K8S pod subnet to be used by the network plugin
POD_NETWORK           CALICO or FLANNEL others aren't supported
LOAD_BALANCER_PORT    6443 only change this if you feel adventerous
MASTER_IPS            a list of all masters IP addresses
MASTERS               a list of all masters **short** hosnames
LOAD_BALANCER_IP      the IP address of the load balancer. DON'T set if you have LOAD_BALANCER_DNS
LOAD_BALANCER_DNS     the DNS name of the load balancer. DON'T set if you have LOAD_BALANCER_IP
BOOTSTRAP_TOKEN       set this for initial value of the bootstrap token or leave empty.
OPENSTACK             NEVER change this on baremetal, leave this 0
SSH_USER              the name of the user that SSH on all machines, must be able to `sudo`
K8SNODES              the list of worker nodes to join the cluster
==================    ==========================================================

Prior configuration before you run the script:
----------------------------------------------

Kuberentes and etcd are especially sensitive to this. Hence, you must make sure
that the command hostname on all your hosts returns only the short name, e.g:

.. code:: shell

   $ hostname
   myhost

   # wrong !
   myhost.noris.de

If your `/etc/hosts` file has entries with FQDN name, they should be removed too.
You should remove all search domain from `resolv.conf`!
For example:

.. code:: shell

   sed -i 's/'$(hostname -s)'.noriscloud //g' /etc/hosts
   sed -i 's/^search/#search/g' /etc/resolv.conf

Finally, make sure all swaps and firewall are disabled on all hosts!

