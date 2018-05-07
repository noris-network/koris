====
kolt
====

launch kubernetes clusters on OpenStack using ansible-kubespray



Features
--------

* Get you kubernetes cluster on noris.cloud in about 5 minutes.

Usage
-----

Pre-requisits
~~~~~~~~~~~~~~

1. An OS_RC_FILE, you should download it from the openstack WebUI.
2. A pre-created network, and security group.
3. Basic understanding of OpenStack.
4. Ansible installed on your system.


Get started
~~~~~~~~~~~

1. Clone your colt locally:

.. code:: shell

   $ git clone git@gitlab.noris.net:PI/kolt.git

2. Install colt to your system:

.. code:: shell

   $ python3 setup.py install

3. edit your own configuration file:

.. code:: shell

   $ editor docs/k8s-machines-config.yml

You need to have some things pre-created, but the file is self explaining.

4. clone kubespray:

.. code:: shell

   $ git clone -b 'v2.4.0' --single-branch --depth 1 git@github.com:kubernetes-incubator/kubespray.git

5. You should now edit the file `kubespray/inventory/group_vars/all.yml` and set the and set options as you like, for example:

.. code::

   bootstrap_os: ubuntu

6. Edit the file `kubespray/inventory/group_vars/k8s-cluster.yml` and set the following options:

.. code::

   kube_network_plugin: calico
   cluster_name: your-cluster-name.local
   dashboard_enabled: true

7. Note for people with ansible pre-knowledge, **YOU DON'T** need to create your own inventory file, it will be automatically created for you.

8. Run colt with your cluster configuration, this will create your inventory

.. code:: shell

   $ kolt k8s-machines-config.yml -i mycluster.ini

This last step takes about one minute to complete.
Save the above inventory file ``mycluster.ini`` to ``inventory/local/``.

9. Run ansible kubespray on your newly created machines:

.. code:: shell
   $ cd kubespray
   $ ansible-playbook -i  inventory/local/mycluster.ini cluster.yml \
     --ssh-extra-args="-o StrictHostKeyChecking=no" -u ubuntu \
     -e ansible_python_interpreter="/usr/bin/python3" -b


Known Issues
------------

Creating OS machines with floating IPS is still not implemented. You need
to run colt and ansible on a machine which can access your kubernetes cluster
via ssh or your should run ansible via a bastion host.


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage

A thanks to @jlehmannrichter, who made the work preceded this project, and answered
my questions about ansible and kubespray.

.. highlight:: shell
