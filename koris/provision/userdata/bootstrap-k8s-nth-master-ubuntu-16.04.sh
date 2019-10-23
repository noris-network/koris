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

#### Versions for Kube 1.14.1
export KUBE_VERSION=${KUBE_VERSION:-1.14.1}
export AUTO_JOIN=${AUTO_JOIN:-0}
export DOCKER_VERSION=18.06
export CALICO_VERSION=3.3

export KUBECONFIG=/etc/kubernetes/admin.conf

TRANSPORT_PACKAGES="apt-transport-https ca-certificates software-properties-common"

LOGLEVEL=4
V=${LOGLEVEL}

LOGFILE=/dev/stderr

function log() {
	datestring=`date +"%Y-%m-%d %H:%M:%S"`
	echo -e "$datestring - $@" | tee $LOGFILE
}

# check if a binary version is found
# version_check kube-scheduler --version v1.10.4 return 1 if binary is found
# in that version
function version_found() {  return $("$1" "$2" | grep -qi "$3"); }

# enforce docker version
function get_docker() {
    log "stated ${FUNCNAME[0]}"
    dpkg -l software-properties-common | grep ^ii || apt-get install ${TRANSPORT_PACKAGES} -y
    curl --retry 10 -fssl https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    apt-get update
    apt-get -y install docker-ce="${DOCKER_VERSION}*"
    apt-get install -y socat conntrack ipset
    log "Finished ${FUNCNAME[0]}"
}

# enforce kubeadm version
function get_kubeadm {
    log "stated ${FUNCNAME[0]}"
    dpkg -l software-properties-common | grep ^ii || apt-get install ${TRANSPORT_PACKAGES} -y
    curl --retry 10 -fssL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    apt-get install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00
    log "Finished ${FUNCNAME[0]}"
}


function fetch_all() {
    get_docker
    get_kubeadm
}


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


function fetch_secrets(){
    mkdir -pv /etc/kubernetes/pki/etcd

    kubectl get secrets -n kube-system cluster-ca -o json | jq -r '.data["tls.crt"]' | base64 -d > /etc/kubernetes/pki/ca.crt
    kubectl get secrets -n kube-system cluster-ca -o json | jq -r '.data["tls.key"]' | base64 -d > /etc/kubernetes/pki/ca.key

    kubectl get secrets -n kube-system front-proxy -o json | jq -r '.data["tls.crt"]' | base64 -d > /etc/kubernetes/pki/front-proxy-ca.crt
    kubectl get secrets -n kube-system front-proxy -o json | jq -r '.data["tls.key"]' | base64 -d > /etc/kubernetes/pki/front-proxy-ca.key

    kubectl get secrets -n kube-system etcd-ca -o json | jq -r '.data["tls.crt"]' | base64 -d > /etc/kubernetes/pki/etcd/ca.crt
    kubectl get secrets -n kube-system etcd-ca -o json | jq -r '.data["tls.key"]' | base64 -d > /etc/kubernetes/pki/etcd/ca.key

    kubectl get secrets -n kube-system sa-key -o "jsonpath={.data['sa\.key']}" | base64 -d > /etc/kubernetes/pki/sa.key
    kubectl get secrets -n kube-system sa-pub -o "jsonpath={.data['sa\.pub']}" | base64 -d > /etc/kubernetes/pki/sa.pub

    kubectl get cm -n kube-system audit-policy -o="jsonpath={.data['audit-policy\.yml']}" > /etc/kubernetes/audit-policy.yml

    kubectl get secret -n kube-system cloud-config -o="jsonpath={.data['cloud-config']}" | base64 -d > /etc/kubernetes/cloud-config

    # this should be reviewed
    set +e
    kubectl get secret oidc-ca -n kube-system && { kubectl get secret oidc-ca -n kube-system -o="jsonpath={.data['oidc\.ca']}" > /etc/kubernetes/pki/oidc.ca; }
    kubectl get cm -n kube-system dex.tmpl && { kubectl get cm dex.tmpl -n kube-system -o="jsonpath={.data['dex\.tmpl']}" > /etc/kubernetes/dex.tmpl; }
    set -e
}

function write_join_config() {
    log "Started ${FUNCNAME[0]}"
    DISCOVERY_HASH=$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
                     openssl rsa -pubin -outform der 2>/dev/null | \
                     openssl dgst -sha256 -hex | sed 's/^.* //')
    cat <<EOF > /etc/kubernetes/join.yml
apiVersion: kubeadm.k8s.io/v1beta1
discovery:
  bootstrapToken:
    apiServerEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
    token: ${BOOTSTRAP_TOKEN}
    caCertHashes:
     - "sha256:${DISCOVERY_HASH}"
    unsafeSkipCAVerification: false
  timeout: 5m0s
kind: JoinConfiguration
nodeRegistration:
  criSocket: /var/run/dockershim.sock
controlPlane:
  LocalAPIEndpoint:
    advertiseAddress: $(hostname --ip-address)
    bindPort: ${LOAD_BALANCER_PORT}
EOF
    log "Finished ${FUNCNAME[0]}"
}

# the entry point of the whole script.
# this function bootstraps the who etcd cluster and control plane components
# accross N hosts
function main() {

    kubeadm version | grep -qi "${KUBE_VERSION}" || fetch_all
    kubeadm config images pull
    config_pod_network
    if [ ${AUTO_JOIN} -eq 1 ]; then
        fetch_secrets
        write_join_config
        kubeadm join --config /etc/kubernetes/join.yml
    fi
    echo "Success! ${HOSTNAME} should now be part of the cluster."
}


# The script is called as user 'root' in the directory '/'. Since we add some
# files we want to change to root's home directory.
cd /root
main
