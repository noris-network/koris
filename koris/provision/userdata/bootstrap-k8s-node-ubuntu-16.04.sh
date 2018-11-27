text/x-shellscript
#!/bin/bash
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!
# MAKE SURE THIS MATCHED THE MASTER K8S VERSION
#KUBE_VERSION="1.12.2"
KUBE_VERSION="1.11.4"

iptables -P FORWARD ACCEPT
swapoff -a

cat << EOF > /etc/kubernetes/cluster-info.yaml
---
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: ${B64_CA_CONTENT}
    server: https://${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:$LOAD_BALANCER_PORT;
  name: ""
contexts: []
current-context: ""
kind: Config
preferences: {}
users: []
EOF

# config for 1.11.4
cat << EOF > /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml
apiVersion: kubeadm.k8s.io/v1alpha1
kind: NodeConfiguration
discoveryFile: /etc/kubernetes/cluster-info.yaml
nodeName: $(hostname -s)
tlsBootstrapToken: ${BOOTSTRAP_TOKEN}
discoveryTokenCACertHashes:
  sha256:${DISCOVERY_HASH}
EOF

# config for 1.12.2
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
tlsBootstrapToken: ${BOOTSTRAP_TOKEN}
EOF

# join !
until kubeadm -v=10 join --config /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml ${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:$LOAD_BALANCER_PORT;
    do sudo kubeadm reset --force
done
