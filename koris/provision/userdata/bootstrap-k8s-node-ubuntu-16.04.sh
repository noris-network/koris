#!/bin/bash
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!
# MAKE SURE THIS MATCHED THE MASTER K8S VERSION
export KUBE_VERSION=1.12.3
export DOCKER_VERSION=18.06

iptables -P FORWARD ACCEPT
swapoff -a

# load koris environment file if available
if [ -f /etc/kubernetes/koris.env ]; then
    source /etc/kubernetes/koris.env
fi

# bootstrap the node

cat << EOF > /etc/kubernetes/cluster-info.yaml
---
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: ${B64_CA_CONTENT}
    server: https://${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}
  name: ""
contexts: []
current-context: ""
kind: Config
preferences: {}
users: []
EOF

# config for 1.12.3
if [ "$KUBE_VERSION" = "1.12.3" ]; then
  cat << EOF > /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml
---
apiVersion: kubeadm.k8s.io/v1alpha2
clusterName: kubernetes
discoveryFile: /etc/kubernetes/cluster-info.yaml
discoveryTimeout: 15m0s
discoveryTokenUnsafeSkipCAVerification: true
kind: NodeConfiguration
nodeRegistration:
  criSocket: /var/run/dockershim.sock
  name: $(hostname -s)
tlsBootstrapToken: "${BOOTSTRAP_TOKEN}"
EOF
fi

function fetch_all() {
    apt-get update
    apt-get install -y software-properties-common
    curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00

    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    apt-get update
    apt -y --allow-downgrades install docker-ce=${DOCKER_VERSION}*
    apt install -y socat conntrack ipset
}

# check if a binary version is found
# version_check kube-scheduler --version v1.10.4 return 1 if binary is found
# in that version
function version_found() {  return $($1 $2 | grep -qi $3); }

version_found docker $DOCKER_VERSION || fetch_all

# join !
until kubeadm -v=10 join --config /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml ${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:$LOAD_BALANCER_PORT
    do sudo kubeadm reset --force
done
