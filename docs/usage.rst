=====
Usage
=====

To use kolt with kubespray 2.4::

    
    git clone -b 'v2.4.0' --single-branch --depth 1 git@github.com:kubernetes-incubator/kubespray.git
    
    cd kubespray
    kolt k8s-machines-config.yml -i inventory/mycluster.ini
    
    
To use kold with kubespray 2.5::

    git clone -b 'v2.5.0' --single-branch --depth 1 git@github.com:kubernetes-incubator/kubespray.git
    cd kubespray
    kolt k8s-machines-config.yml -i inventory/local/mycluster.ini