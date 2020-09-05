"""

.. _userdata:

kiosk.provison.userdata
-----------------------

bootstrap-k8s-master-ubuntu-16.04.sh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This script is executed on the first master on cluster boot.
One can also run this script on bare metal machines to create
a ``kubeadm`` based kubernetes cluster.

The script needs ``/etc/kubernetes/kiosk.env`` to run properly.
This file includes all the information on the cluster and
written via ``cloud-init`` on the first boot.
See :py:class:`kiosk.provision.cloud_init.FirstMasterInit`

.. literalinclude:: ../kiosk/provision/userdata/bootstrap-k8s-master-ubuntu-16.04.sh
   :language: shell

bootstrap-k8s-nth-master-ubuntu-16.04.sh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This script is executed on the nth master upon initial bootstrap.

.. literalinclude:: ../kiosk/provision/userdata/bootstrap-k8s-nth-master-ubuntu-16.04.sh
   :language: shell

bootstrap-k8s-node-ubuntu-16.04.sh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. literalinclude:: ../kiosk/provision/userdata/bootstrap-k8s-node-ubuntu-16.04.sh
   :language: shell

"""
