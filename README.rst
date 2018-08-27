====
kolt
====

Launch kubernetes clusters on OpenStack.
Kolt supports two work modes:

1. In the first mode you create an empty cluster on Openstack,
   and recieve an inventory for usage with ansible-kubespray.

2. In the second mode (still in alpha) you boot a cluster on openstack.
   You then recieve a working `kubeconfig` file.


Features
--------

* Get you kubernetes cluster on noris.cloud in about 5 minutes.

Demo:

.. image:: https://gitlab.noris.net/PI/kolt/raw/dev/docs/static/_imgs/kolt-demo.gif
   :target: https://gitlab.noris.net/PI/kolt/raw/dev/docs/static/_imgs/kolt-demo.gif
   :scale: 22%
   :width: 200 px

Usage
-----

Pre-requisits
~~~~~~~~~~~~~

1. An OS_RC_FILE v3, you should download it from the openstack WebUI.
2. A pre-created network, and security group.
3. Basic understanding of OpenStack.
4. Ansible installed on your system (only if using kubespray mode).

Get started
~~~~~~~~~~~
1. Create a local virtual environment for kolt:

.. code:: shell

   mkdir FooBar
   cd FooBar && pipenv --python 3.6
   pip install -e git+git@gitlab.noris.net:PI/kolt.git@v0.3#egg=kolt

If you want to develop kolt, you can use the following install command in the
virtual environment:

.. code:: shell

    pipenv install --dev -r requirements.txt
    pipenv install --dev -r requirements_dev.txt

2. Create a security group in openstack which allows `ipip` and `BGP` protocol.

.. code:: shell

   neutron security-group-create foo
   neutron security-group-rule-create --protocol 0 --direction egress foo
   neutron security-group-rule-create --protocol 0 --direction ingress foo
   neutron security-group-rule-create  --protocol 4  --direction egress foo
   neutron security-group-rule-create  --protocol 4  --direction igress foo
   neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --direction egress foo
   neutron security-group-rule-create --protocol tcp --port-range-min 179 --port-range-max 179 --direction ingress foo

2. edit your own configuration file:

.. code:: shell

   $ editor k8s-machines-config.yml

See the `source repository`_ `docs/k8s-machines-config.yml` for an example.

.. _source repository: https://gitlab.noris.net/PI/kolt/blob/dev/docs/k8s-machines-config.yml

3. clone kubespray:

.. code:: shell

   $ git clone -b 'v2.5.0' --single-branch --depth 1 git@github.com:kubernetes-incubator/kubespray.git

4. You should now edit the file `kubespray/inventory/group_vars/all.yml`
   and set the and set options as you like, for example:

.. code::

   bootstrap_os: ubuntu

You must set the following option:

.. code::

   cloud_provider: openstack

5. Edit the file `kubespray/inventory/group_vars/k8s-cluster.yml`
   and set the following options:

.. code::

   kube_network_plugin: calico
   cluster_name: your-cluster-name.local
   dashboard_enabled: true

6. Note for people with ansible pre-knowledge, **YOU DON'T** need to create your
   own inventory file, it will be automatically created for you.

7. Run colt with your cluster configuration, this will create your
   inventory (the file ``k8s-machines-config.yml`` can be found in the directory
   ``kolt/docs``, so change to this directory before issuing the next command)

.. code:: shell

   $ kolt kubespray k8s-machines-config.yml -i mycluster.ini

This last step takes about one minute to complete.

.. important::
   
   Copy the above inventory file ``mycluster.ini`` to ``kubespray/inventory/``
   with the following command (you may need to adjust the path if you
   cloned kubespray to some other location).

.. code:: shell

   $ cp mycluster.ini ../../kubespray/inventory/

8. Run ansible kubespray on your newly created machines.

.. note::
   You **must** to call the `ansible-playbook` command from the `kubespray` directory.

.. code:: shell

   $ cd kubespray
   $ ansible-playbook -i  inventory/mycluster.ini cluster.yml \
     --ssh-extra-args="-o StrictHostKeyChecking=no" -u ubuntu \
     -e ansible_python_interpreter="/usr/bin/python3" -b --flush-cache


Known Issues
------------

Creating OS machines with floating IPS is still not implemented. You need
to run colt and ansible on a machine which can access your kubernetes cluster
via ssh or your should run ansible via a bastion host.

If you encounter the following message before failure:

.. code:: shell

   RUNNING HANDLER [kubernetes/master : Master | wait for the apiserver to be running] **********
   Wednesday 09 May 2018  10:04:27 +0000 (0:00:00.449)       0:13:00.785 *********
   FAILED - RETRYING: Master | wait for the apiserver to be running (20 retries left).
   FAILED - RETRYING: Master | wait for the apiserver to be running (20 retries left).
   FAILED - RETRYING: Master | wait for the apiserver to be running (19 retries left).
   FAILED - RETRYING: Master | wait for the apiserver to be running (19 retries left).

Check on your masters that the kubelet service can start:

.. code:: shell

   ssh master1
   sudo journalctl -u kubelet

This should give you some hint how to fix the problem.

You should also check that you have a properly created ``cloud_config`` file:

.. code:: shell

   root@master-2-nude:/home/ubuntu# cat /etc/kubernetes/cloud_config
   [Global]
   auth-url="https://de-nbg6-1.noris.cloud:5000/v3"
   username="*********YOUR_USER**********"
   password="*********YOUR_PASSWORD********"
   region="de-nbg6-1"
   tenant-id="********YOUR_TENNANT_ID*************"
   domain-name="noris.de"


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage

A thanks to @jlehmannrichter, who made the work preceded this project, and answered
my questions about ansible and kubespray.

.. highlight:: shell
