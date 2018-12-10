#!/bin/bash

# TODO: This script can be removed if the koris image contains the
# kubeadm script.

set -e

iptables -P FORWARD ACCEPT
swapoff -a

# install kubeadm if not already done
export KUBE_VERSION="1.12.3"
sudo apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
sudo apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00
