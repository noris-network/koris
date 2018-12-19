#!/bin/bash

###
# install nth master required packages if not alredy installed
###

set -e

iptables -P FORWARD ACCEPT
swapoff -a

# load koris environment file if available
if [ -f /etc/kubernetes/koris.env ]; then
    source /etc/kubernetes/koris.env
fi

#### Versions for Kube 1.12.3
export KUBE_VERSION=1.12.3
export DOCKER_VERSION=18.06
export CALICO_VERSION=3.3


LOGLEVEL=4
V=${LOGLEVEL}

function fetch_all() {
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    sudo swapoff -a
    curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    sudo apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    sudo apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00

    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    sudo apt-get update
    sudo apt-get -y install docker-ce=${DOCKER_VERSION}*
    sudo apt install -y socat conntrack ipset
}

# the entry point of the whole script.
# this function bootstraps the who etcd cluster and control plane components
# accross N hosts
function main() {
    fetch_all
}


# The script is called as user 'root' in the directory '/'. Since we add some
# files we want to change to root's home directory.
cd /root

main
