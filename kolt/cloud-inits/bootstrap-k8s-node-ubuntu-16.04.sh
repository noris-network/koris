text/x-shellscript
#!/bin/sh
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# Specify the Kubernetes version to use.
HYPERKUBE_VERSION="v1.9.2_coreos.0"
DOCKER_VERSION="17.05.0~ce-0~ubuntu-xenial"
ETCDVERSION="v3.2.4"

sudo apt-get remove -y docker docker-engine docker.io

sudo apt-get update -y
sudo apt-get install -y \
    socat \
    apt-transport-https \
    ca-certificates \
    curl \
	ebtables \
	software-properties-common \
	cloud-utils

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
sudo add-apt-repository \
   "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) \
   stable"


sudo apt-get update && apt-get install -y docker-engine=${DOCKER_VERSION}

sudo systemctl enable docker
sudo systemctl start docker
sudo docker pull quay.io/coreos/hyperkube:${HYPERKUBE_VERSION}
