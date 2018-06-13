=====
Usage
=====

To use kolt with kubespray 2.4::

    
    git clone -b 'v2.4.0' --single-branch --depth 1 git@github.com:kubernetes-incubator/kubespray.git
    cd kubespray
    kolt k8s-machines-config.yml -i inventory/mycluster.ini
        ansible-playbook -i inventory/mycluster.ini cluster.yml  --ssh-extra-args="-o StrictHostKeyChecking=no" -u ubuntu  -e ansible_python_interpreter="/usr/bin/python3" -b --flush-cache
    
    
To use kolt with kubespray 2.5::

    git clone -b 'v2.5.0' --single-branch --depth 1 git@github.com:kubernetes-incubator/kubespray.git
    cd kubespray
    kolt k8s-machines-config.yml -i inventory/local/mycluster.ini
    source ~/OS-RC-FILE-v2 
    ansible-playbook -i inventory/local/mycluster.ini cluster.yml  --ssh-extra-args="-o StrictHostKeyChecking=no" -u ubuntu  -e ansible_python_interpreter="/usr/bin/python3" -b --flush-cache