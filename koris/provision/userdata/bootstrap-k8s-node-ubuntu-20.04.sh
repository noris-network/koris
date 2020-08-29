#!/bin/bash
set -e
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!
# MAKE SURE THIS MATCHED THE MASTER K8S VERSION
# load koris environment file if available
if [ -f /etc/kubernetes/koris.env ]; then
	# shellcheck disable=SC1091
    source /etc/kubernetes/koris.env
fi

LOGFILE=/dev/stderr

function log() {
	datestring=`date +"%Y-%m-%d %H:%M:%S"`
	echo -e "$datestring - $@" | tee $LOGFILE
}

KUBE_VERSION_COMPARE="$(echo "${KUBE_VERSION}" | cut -d '.' -f 2 )"

export KUBE_VERSION=${KUBE_VERSION:-1.14.1}
export DOCKER_VERSION=${DOCKER_VERSION:-"1.19"}
TRANSPORT_PACKAGES="apt-transport-https ca-certificates curl software-properties-common gnupg2"

iptables -P FORWARD ACCEPT
swapoff -a


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

cat << EOF > /etc/kubernetes/kubeadm-node-"${KUBE_VERSION}".yaml
---
apiVersion: kubeadm.k8s.io/v1beta1
discovery:
  bootstrapToken:
    apiServerEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
    token: ${BOOTSTRAP_TOKEN}
    caCertHashes:
     - "sha256:${DISCOVERY_HASH}"
    unsafeSkipCAVerification: false
  timeout: 15m0s
kind: JoinConfiguration
nodeRegistration:
  criSocket: /var/run/dockershim.sock
EOF

function get_kubeadm {
    log "started ${FUNCNAME[0]}"
    dpkg -l software-properties-common | grep ^ii || apt-get install ${TRANSPORT_PACKAGES} -y
    curl --retry 10 -fssL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    apt-get install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00
    log "Finished ${FUNCNAME[0]}"
}

function get_docker() {
    log "Started get_docker"
    apt-get update
    dpkg -l software-properties-common | grep ^ii || apt-get install ${TRANSPORT_PACKAGES} -y
    curl --retry 10 -fssl https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    apt-get update
    apt-get install -y socat conntrack ipset
    apt-get update && apt-get install -y \
       containerd.io=1.2.13-2 \
       docker-ce=5:19.03.11~3-0~ubuntu-$(lsb_release -cs) \
       docker-ce-cli=5:19.03.11~3-0~ubuntu-$(lsb_release -cs)
    cat > /etc/docker/daemon.json <<EOF
{
  "exec-opts": ["native.cgroupdriver=systemd"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m"
  },
  "storage-driver": "overlay2"
}
EOF
    mkdir -p /etc/systemd/system/docker.service.d
    # Restart Docker
    systemctl daemon-reload
    systemctl restart docker
    systemctl enable docker
    log "Finished ${FUNCNAME[0]}"
}
# check if a binary version is found
# version_check kube-scheduler --version v1.10.4 return 1 if binary is found
# in that version
function version_found() {  return $("$1" "$2" | grep -qi "$3"); }


# run commands needed for network plugins
function config_pod_network(){
    case "${POD_NETWORK}" in
        "CALICO")
            ;;
        "FLANNEL")
            sysctl net.bridge.bridge-nf-call-iptables=1
            ;;
    esac
}

function join() {
	kubeadm -v=10 join --config /etc/kubernetes/kubeadm-node-"${KUBE_VERSION}".yaml "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
}

function main() {

    version_found docker --version "${DOCKER_VERSION}" || for i in $(seq 1 10); do (get_docker && break; sleep 30); done
    version_found kubeadm version "${KUBE_VERSION}" || for i in $(seq 1 10); do (get_kubeadm && break; sleep 30); done
    config_pod_network

    # join !
    until join; do sudo kubeadm reset --force
    done
}

# This line and the if condition bellow allow sourcing the script without executing
# the main function
(return 0 2>/dev/null) && sourced=1 || sourced=0

if [[ $sourced == 1 ]]; then
    set +e
    echo "You can now use any of these functions:"
    echo ""
    typeset -F |  cut -d" " -f 3
else
    set -eu
    cd /root
    iptables -P FORWARD ACCEPT
    swapoff -a
    main "$@"
fi

# vi: ts=4 sw=4 ai
