"""

.. _userdata:

koris.provison.userdata
-----------------------

bootstrap-k8s-master-ubuntu-16.04.sh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This script is executed on the first master on cluster boot.
One can also run this script on bare metal machines to create
a ``kubeadm`` based kubernetes cluster.

The script needs ``/etc/kubernetes/koris.env`` to run properly.
This file includes all the information on the cluster and
written via ``cloud-init`` on the first boot.
See :py:class:`koris.provision.cloud_init.FirstMasterInit`

.. literalinclude:: ../koris/provision/userdata/bootstrap-k8s-master-ubuntu-16.04.sh
   :language: shell

bootstrap-k8s-nth-master-ubuntu-16.04.sh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This script is executed on the nth master upon initial bootstrap.

.. literalinclude:: ../koris/provision/userdata/bootstrap-k8s-nth-master-ubuntu-16.04.sh
   :language: shell

bootstrap-k8s-node-ubuntu-16.04.sh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. literalinclude:: ../koris/provision/userdata/bootstrap-k8s-node-ubuntu-16.04.sh
   :language: shell

"""
