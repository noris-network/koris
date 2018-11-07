text/x-shellscript
#!/bin/bash
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!
KUBE_VERSION="1.11.4"

sudo apt-get update
sudo apt-get install -y software-properties-common
sudo swapoff -a
sudo curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
sudo apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 \
	kubelet=${KUBE_VERSION}-00 kubectl=${KUBE_VERSION}-00

sudo "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -"
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
sudo apt-get update
sudo apt-get -y install docker-ce

sudo mkdir -p /etc/kubernetes/pki/etcd
