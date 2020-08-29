#!/bin/bash

set -e

###
# A script to create a HA K8S cluster on OpenStack using pure bash and kubeadm
#
# The script is devided into a whole bunch of functions, look for the fuction
# called main at the bottom.
#
# The script will create mutliple kubernetes control plane members connected
# via an etcd cluster which is grown in a serial manner. That means we first
# create a single etcd host, and then add N hosts one after another.
#
# The addition of master nodes is done via SSH!
#
# This should be the content of /etc/kubernetes/koris.env
#
#	export BOOTSTRAP_NODES=1  # for bootstrapping baremetal nodes (i.e. not an Openstack Image
#	export SSH_USER="root"    # for ubuntu use ubuntu
#	export POD_SUBNET="10.233.0.0/16"
#	export POD_NETWORK="CALICO"
#	export LOAD_BALANCER_PORT="6443"
#	export MASTERS_IPS=( 10.32.10.1  10.32.10.2 10.32.10.3 )
#	export MASTERS=( master-1 master-2 master-3 )
#   # specify one of the two LOAD_BALANCER_IP or LOAD_BALANCER_DNS
#	export LOAD_BALANCER_IP=XX.YY.ZZ.WW
#	export BOOTSTRAP_TOKEN=$(openssl rand -hex 3).$$(openssl rand -hex 8)
#	export OPENSTACK=0
#	export K8SNODES=( node-1 node-2 ) # a list of nodes to join
#
###

# load koris environment file if available
if [ -f /etc/kubernetes/koris.env ]; then
    source /etc/kubernetes/koris.env
fi

export CURRENT_CLUSTER=""
export CLUSTER_STATE=""


#### Versions for Kube 1.12.X
export KUBE_VERSION=${KUBE_VERSION:-1.14.1}
export POD_SUBNET=${POD_SUBNET:-"10.233.0.0/16"}
export SSH_USER=${SSH_USER:-"ubuntu"}
export BOOTSTRAP_NODES=${BOOTSTRAP_NODES:-0}
export OPENSTACK=${OPENSTACK:-1}
export K8SNODES=${K8SNODES:-""}
export OIDC_CLIENT_ID=${OIDC_CLIENT_ID:-""}
export OIDC_CA_FILE=${OIDC_CA_FILE:-""}
export ADDTOKEN=1

# find if better way to compare versions exists
# version numbers are splited in the "." and the second part is being compared
# ex. "1.12 vs 1.13 means compare 12 with 13"
KUBE_VERSION_COMPARE="$(echo $KUBE_VERSION | cut -d '.' -f 2 )"

LOGLEVEL=4
V=${LOGLEVEL}

LOGFILE=/dev/stderr

function log() {
	datestring=`date +"%Y-%m-%d %H:%M:%S"`
	echo -e "$datestring - $@" | tee $LOGFILE
}

SSHOPTS="-i /etc/ssh/ssh_host_rsa_key -o StrictHostKeyChecking=no -o ConnectTimeout=60"
SFTPOPTS=${SSHOPTS}

# used for k8s v1.13.X
function create_kubeadm_config_new_version () {
    HOST_NAME=$1
    HOST_IP=$2

    cat <<TMPL > kubeadm-"${HOST_NAME}".yaml
apiVersion: kubeadm.k8s.io/v1beta1
kind: ClusterConfiguration
kubernetesVersion: v${KUBE_VERSION}
apiServer:
  certSANs:
  - "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}"
controlPlaneEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
networking:
  # This CIDR is a Calico default. Substitute or remove for your CNI provider.
  podSubnet: ${POD_SUBNET}
  # dnsDomain: cluster.local
  # serviceSubnet: 10.96.0.0/12
controllerManager:
  extraArgs:
    allocate-node-cidrs: "true"
    cluster-cidr: ${POD_SUBNET}
  extraArgs:
    external-cloud-volume-plugin: "openstack"
    cloud-config: /etc/kubernetes/cloud-config
  extraVolumes:
   - hostPath: /etc/kubernetes/cloud-config
     name: cloud-config
     mountPath: /etc/kubernetes/cloud-config
     pathType: File
TMPL

# If Dex is to be deployed, we need to start the apiserver with extra args.
if [[ ! -z ${OIDC_CLIENT_ID} ]]; then
cat <<TMPL > dex.yaml
apiServer:
  extraArgs:
    oidc-issuer-url: "${OIDC_ISSUER_URL}"
    oidc-client-id: ${OIDC_CLIENT_ID}
    oidc-ca-file: ${OIDC_CA_FILE}
    oidc-username-claim: ${OIDC_USERNAME_CLAIM}
    oidc-groups-claim: ${OIDC_GROUPS_CLAIM}
TMPL
yq m -i -a kubeadm-"${HOST_NAME}".yaml dex.yaml
fi

# add audit policy
cat <<AUDITPOLICY >> auditPolicy.yml
apiServer:
  extraArgs:
    audit-log-maxsize: "24"
    audit-log-maxbackup: "30"
    audit-log-maxage: "90"
    audit-log-path: /var/log/kubernetes/audit.log
    audit-policy-file: /etc/kubernetes/audit-policy.yml
AUDITPOLICY

yq m -i -a kubeadm-"${HOST_NAME}".yaml auditPolicy.yml

# add volumes for audit logs
cat << AV >> auditVolumes.yml
apiServer:
  extraVolumes:
  - name: var-log-kubernetes
    hostPath: /var/log/kubernetes
    mountPath: /var/log/kubernetes
    pathType: DirectoryOrCreate
  - name: "audit-policy"
    hostPath: "/etc/kubernetes/audit-policy.yml"
    mountPath: "/etc/kubernetes/audit-policy.yml"
    readOnly: true
    pathType: File
AV

yq m -i -a kubeadm-"${HOST_NAME}".yaml auditVolumes.yml

if [[ ${ADDTOKEN} -eq 1 ]]; then
cat <<TOKEN >> kubeadm-"${HOST_NAME}".yaml
---
apiVersion: kubeadm.k8s.io/v1beta1
kind: InitConfiguration
bootstrapTokens:
- groups:
  - system:bootstrappers:kubeadm:default-node-token
  token: ${BOOTSTRAP_TOKEN}
  ttl: 24h0m0s
  usages:
  - signing
  - authentication
nodeRegistration:
  criSocket: /var/run/dockershim.sock
  name: ${HOSTNAME}
  taints:
  - effect: NoSchedule
    key: node-role.kubernetes.io/master
TOKEN
fi

DISCOVERY_HASH=$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
                 openssl rsa -pubin -outform der 2>/dev/null | \
                 openssl dgst -sha256 -hex | sed 's/^.* //')

}

# create secrets and config maps
# these are used by the master pod which we call from the CLI
function make_secrets() {
    local k8senv="--kubeconfig=/etc/kubernetes/admin.conf -n kube-system"
    local del_secret_args="${k8senv} --ignore-not-found=true delete secret"
    local secret_args="${k8senv} create secret"

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} ssh-key
    # shellcheck disable=SC2086
    kubectl ${secret_args} generic ssh-key --from-file=/etc/ssh/ssh_host_rsa_key

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} "cluster-ca"
    # shellcheck disable=SC2086
    kubectl ${secret_args} tls "cluster-ca" --key /etc/kubernetes/pki/ca.key --cert /etc/kubernetes/pki/ca.crt

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} "front-proxy"
    # shellcheck disable=SC2086
    kubectl ${secret_args} tls "front-proxy" --key /etc/kubernetes/pki/front-proxy-ca.key --cert /etc/kubernetes/pki/front-proxy-ca.crt

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} "etcd-ca"
    # shellcheck disable=SC2086
    kubectl ${secret_args} tls "etcd-ca" --key /etc/kubernetes/pki/etcd/ca.key --cert /etc/kubernetes/pki/etcd/ca.crt

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} "sa-pub"
    # shellcheck disable=SC2086
    kubectl ${secret_args} generic "sa-pub" --from-file=/etc/kubernetes/pki/sa.pub

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} "sa-key"
    # shellcheck disable=SC2086
    kubectl ${secret_args} generic "sa-key" --from-file=/etc/kubernetes/pki/sa.key

    # shellcheck disable=SC2086
    kubectl ${del_secret_args} admin.conf
    # shellcheck disable=SC2086
    kubectl ${secret_args} generic admin.conf --from-file=/etc/kubernetes/admin.conf

    # shellcheck disable=SC2086
    kubectl ${k8senv} create configmap audit-policy --from-file="/etc/kubernetes/audit-policy.yml"
    kubectl ${k8senv} create configmap kubeadm.yaml --from-file="kubeadm.yaml"

    if [[ ${OPENSTACK} -eq 1 ]]; then
        # shellcheck disable=SC2086
        kubectl ${del_secret_args} cloud-config
        kubectl ${del_secret_args} cloud-config
        # shellcheck disable=SC2086
        kubectl ${secret_args} generic cloud-config --from-file=/etc/kubernetes/cloud-config
    fi

    if [[ ! -z ${OIDC_CA_FILE} ]]; then
        kubectl ${del_secret_args} oidc-ca
        # shellcheck disable=SC2086
        kubectl ${secret_args} generic oidc-ca --from-file="${OIDC_CA_FILE}"
        # shellcheck disable=SC2086
        kubectl ${k8senv} delete configmap dex-config --ignore-not-found=true
        # shellcheck disable=SC2086
        kubectl ${k8senv} create configmap dex-config --from-file="dex.tmpl"
    fi
}


# distributes configuration file and certificates to a master node
function copy_keys() {
    host=$1
    USER=${SSH_USER:-ubuntu}

    echo -n "waiting for ssh on $1"
    until ssh ${SSHOPTS} "${USER}"@"$1" hostname; do
       echo -n "."
       sleep 1
    done

    echo "distributing keys to $host";
    # clean and recreate directory structure
    ssh ${SSHOPTS} ${USER}@$host sudo rm -vRf /etc/kubernetes
    ssh ${SSHOPTS} ${USER}@$host mkdir -pv /home/${USER}/kubernetes/pki/etcd
    ssh ${SSHOPTS} ${USER}@$host mkdir -pv /home/${USER}/kubernetes/manifests

    # copy over everything PKI related, copy to temporary directory with
    # non-root write access
    sftp ${SFTPOPTS} ${USER}@$host << EOF
	put /etc/kubernetes/pki/ca.crt /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/ca.key /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/sa.key /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/sa.pub /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/front-proxy-ca.crt /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/front-proxy-ca.key /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/etcd/ca.crt /home/${USER}/kubernetes/pki/etcd/
	put /etc/kubernetes/pki/etcd/ca.key /home/${USER}/kubernetes/pki/etcd/
	put /etc/kubernetes/admin.conf /home/${USER}/kubernetes/
	chmod 0600 /home/${USER}/kubernetes/admin.conf
	put /etc/kubernetes/koris.env /home/${USER}/kubernetes/
	put /etc/kubernetes/audit-policy.yml /home/${USER}/kubernetes/
EOF
    if [[ ${OPENSTACK} -eq 1 ]]; then
        sftp ${SFTPOPTS} ${USER}@$host << EOF
	put /etc/kubernetes/cloud-config /home/${USER}/kubernetes/
	chmod 0600 /home/${USER}/kubernetes/cloud-config
EOF
    fi

	if [ ! -z "${OIDC_CA_FILE}" ]; then
	     local DESTDIR
	     DESTDIR="$(dirname "${OIDC_CA_FILE}")"
	     ssh ${SSHOPTS} "${USER}@$host" mkdir -pv /home/"${USER}"/"${DESTDIR}"
	     sftp ${SFTPOPTS} "${USER}@$host" << EOF

	put ${OIDC_CA_FILE} /home/${USER}/${DESTDIR}
	chmod 0600 /home/${USER}/${OIDC_CA_FILE}
EOF
    fi

    if [[ ${OPENSTACK} -eq 1 ]]; then
        sftp ${SFTPOPTS} ${USER}@$host << EOF
	put /etc/kubernetes/cloud-config /home/${USER}/kubernetes/
	chmod 0600 /home/${USER}/kubernetes/cloud-config
EOF
    fi

    # move back to /etc on remote machine
    ssh ${SSHOPTS} ${USER}@$host sudo mv -v /home/${USER}/kubernetes /etc/
    ssh ${SSHOPTS} ${USER}@$host sudo chown root:root -vR /etc/kubernetes
    ssh ${SSHOPTS} ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/admin.conf

    echo "done distributing keys to $host";
}

# add audit minimal audit policy
function create_audit_policy(){
if [ ! -r /etc/kubernetes/audit-policy.yml ]; then
   cat << EOF > /etc/kubernetes/audit-policy.yml
# Log all requests at the Metadata level.
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: Metadata
EOF
fi
}

# check if a binary version is found
# version_check kube-scheduler --version v1.10.4 return 1 if binary is found
# in that version
function version_found() {  return $("$1" "$2" | grep -qi "$3"); }


# bootstrap the first master.
# the process is slightly different than for the rest of the N masters
# we add
function bootstrap_first_master() {
   HOST_NAME=$1
   HOST_IP=$2
   CONFIG=kubeadm-${HOST_NAME}.yaml

   CURRENT_CLUSTER="$HOST_NAME=https://${HOST_IP}:2380"

   echo "Bootstaping k8s ${KUBE_VERSION}"
   create_kubeadm_config_new_version "${HOST_NAME}" "${HOST_IP}"
   kubeadm init --config "${CONFIG}"
   kubeadm -v=${V} init phase upload-config all --config "${CONFIG}"

   test -d /root/.kube || mkdir -p /root/.kube
   cp /etc/kubernetes/admin.conf /root/.kube/config
   chown root:root /root/.kube/config
   cp kubeadm-${HOST_NAME}.yaml kubeadm.yaml
   kubectl get nodes
}


function add_master_kubeadm() {
	ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm -v=5 join ${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT} \
		--token ${BOOTSTRAP_TOKEN} \
		--discovery-token-ca-cert-hash \
		 sha256:${DISCOVERY_HASH} \
		--control-plane
}

# add a master to the cluster
# the first argument is the host name to add
# the second argument is the host IP
function add_master {
    set -x
    USER=${SSH_USER:-ubuntu}

    HOST_NAME=$1
    HOST_IP=$2

    local CONFIG="/home/${USER}/kubeadm-${HOST_NAME}.yaml"

    echo "*********** Bootstrapping $1 ******************"
    until ssh ${SSHOPTS} ${USER}@$1 hostname; do
       echo "waiting for ssh on $1"
       sleep 2
    done

    ssh ${SSHOPTS} ${USER}@1 "kubeadm | grep -qi ${KUBE_VERSION}" || BOOTSTRAP_NODES=1
    if [ ${BOOTSTRAP_NODES} -eq 1 ]; then
        bootstrap_deps_node $1
    fi

    echo "******* Preparing kubeadm config for $1 ******"
    echo "bootstrapping 1.13"
    add_master_kubeadm $HOST_NAME $CONFIG
}


function wait_for_etcd () {
    until [[ x"$(kubectl get pod etcd-$1 -n kube-system -o jsonpath='{.status.phase}' 2>/dev/null)" == x"Running" ]]; do
        echo "waiting for etcd-$1 ... "
        sleep 2
    done
}


TRANSPORT_PACKAGES="apt-transport-https ca-certificates curl software-properties-common gnupg2"

# fetch and prepare calico manifests
function get_calico(){
    while [ ! -f tigera-operator.yaml ]; do
        curl --retry 10 -sfLO https://docs.projectcalico.org/manifests/tigera-operator.yaml
    done
    while [ ! -f custom-resources.yaml ]; do
        curl --retry 10 -sfLO https://docs.projectcalico.org/manifests/custom-resources.yaml
	curl --retry 10 -sfLO https://docs.projectcalico.org/manifests/custom-resources.yaml
    done

    sed -i 's@192.168.0.0/16@'"${POD_SUBNET}"'@g' custom-resources.yaml
}


# fetch the manifest for flannel
function get_flannel(){
    while [ ! -r kube-flannel.yml ]; do
         curl --retry 10 -sfLO https://raw.githubusercontent.com/coreos/flannel/bc79dd1505b0c8681ece4de4c0d86c5cd2643275/Documentation/kube-flannel.yml
    done
    sed -i "s@\"Type\": \"vxlan\"@\"Type\": \"ipip\"@g" kube-flannel.yml
    sed -i "s@10.244.0.0/16@${POD_SUBNET}@g" kube-flannel.yml
}

# get the correct network plugin
function get_net_plugin(){
    case "${POD_NETWORK}" in
        "CALICO"|"")
            get_calico
            ;;
        "FLANNEL")
            get_flannel
            sysctl net.bridge.bridge-nf-call-iptables=1
            ;;
    esac
}

# apply the correct network plugin
function apply_net_plugin(){
    case "${POD_NETWORK}" in
        "CALICO"|"")
            echo "installing calico"
            kubectl apply -f tigera-operator.yaml
            kubectl apply -f custom-resources.yaml
            ;;
        "FLANNEL")
            echo "installing flannel"
            kubectl apply -f kube-flannel.yml
            ;;
    esac
}


function bootstrap_deps_node() {
ssh ${SSHOPTS} ${SSH_USER}@${1} sudo bash << EOF
set -ex;
iptables -P FORWARD ACCEPT;
swapoff -a;
export TRANSPORT_PACKAGES="${TRANSPORT_PACKAGES}";
export KUBE_VERSION="${KUBE_VERSION}";
export first_master="${first_master}";
$(typeset -f log);
$(typeset -f get_yq);
$(typeset -f get_docker);
$(typeset -f get_kubeadm);
$(typeset -f fetch_all);
fetch_all;
EOF
}

# enforce docker version
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

# enforce kubeadm version
function get_kubeadm() {
    apt-get update
    dpkg -l software-properties-common | grep ^ii || apt-get install ${TRANSPORT_PACKAGES} -y
    curl --retry 10 -fssL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    apt-get install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00
}

function get_yq() {
	if [ -z "$(type -P yq)" ]; then
		curl --retry 10 -fssL https://github.com/mikefarah/yq/releases/download/2.3.0/yq_linux_amd64 -o /usr/local/bin/yq
		chmod +x /usr/local/bin/yq
	fi
}

# the entry point of the whole script.
# this function bootstraps the who etcd cluster and control plane components
# accross N hosts
function main() {
    get_net_plugin &
    pid_get_net_plugin=$!

    for i in $(seq 1 10); do get_yq && break; sleep 30; done;
    for i in $(seq 1 10); do get_docker && break; sleep 30; done;
    for i in $(seq 1 10); do get_kubeadm && break; sleep 30; done;

    export first_master=${MASTERS[0]}
    export first_master_ip=${MASTERS_IPS[0]}

    bootstrap_first_master "${first_master}" "${first_master_ip}"
    wait_for_etcd "${first_master}"
    make_secrets


    wait $pid_get_net_plugin
    apply_net_plugin

    # this is how we enbale the external CSI provider needed in kubenetes 1.16
    # and later. Current, koris versions will provision volumes with the built
    # in cloud-provider, all other cloud operations go through the external
    # cloud provider
    #kubectl apply -f https://raw.githubusercontent.com/kubernetes/cloud-provider-openstack/master/manifests/cinder-csi-plugin/cinder-csi-controllerplugin-rbac.yaml
    #kubectl apply -f https://raw.githubusercontent.com/kubernetes/cloud-provider-openstack/master/manifests/cinder-csi-plugin/cinder-csi-controllerplugin.yaml
    #kubectl apply -f https://raw.githubusercontent.com/kubernetes/cloud-provider-openstack/master/manifests/cinder-csi-plugin/cinder-csi-nodeplugin-rbac.yaml
    #kubectl apply -f https://raw.githubusercontent.com/kubernetes/cloud-provider-openstack/master/manifests/cinder-csi-plugin/cinder-csi-nodeplugin.yaml
    #kubectl apply -f https://raw.githubusercontent.com/kubernetes/cloud-provider-openstack/master/manifests/cinder-csi-plugin/csi-cinder-driver.yaml

    for (( i=1; i<${#MASTERS[@]}; i++ )); do
        echo "bootstrapping master ${MASTERS[$i]}";
        HOST_NAME=${MASTERS[$i]}
        HOST_IP=${MASTERS_IPS[$i]}
        until add_master $HOST_NAME $HOST_IP; do
            ssh ${SSHOPTS} $HOST_NAME sudo kubeadm reset -f
        done

        wait_for_etcd $HOST_NAME
        echo "done bootstrapping master ${MASTERS[$i]}";
    done

    if [[ -n ${K8SNODES} && "$(declare -p K8SNODES)" =~ "declare -a" ]]; then
        echo "Joining worker nodes ..."
        join_all_hosts
    fi

    echo "the installation has finished."
}

# when building bare metal cluster or vSphere clusters this is used to
# install dependencies on each host and join the host to the cluster
function join_all_hosts() {
   export DISCOVERY_HASH=$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
                           openssl rsa -pubin -outform der 2>/dev/null | \
                           openssl dgst -sha256 -hex | sed 's/^.* //')
   if [ -z ${BOOTSTRAP_TOKEN} ]; then
        export BOOTSTRAP_TOKEN=$(kubeadm token list | grep -v TOK| cut -d" " -f 1 | grep '^\S')
   fi
   for K in "${K8SNODES[@]}"; do
       echo "***** ${K} ******"
       if [ ${BOOTSTRAP_NODES} -eq 1 ]; then
            bootstrap_deps_node ${K}
       fi
       ssh ${K} sudo kubeadm reset -f
       ssh ${K} sudo kubeadm join --token $BOOTSTRAP_TOKEN ${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:$LOAD_BALANCER_PORT --discovery-token-ca-cert-hash sha256:${DISCOVERY_HASH}
   done
}

# keep this function here, although we don't use it really, it's usefull for
# building bare metal cluster or vSphere clusters
function fetch_all() {
    for i in $(seq 1 10); do get_docker && break; sleep 30; done;
    for i in $(seq 1 10); do get_kubeadm && break; sleep 30; done;
}

# The script is called as user 'root' in the directory '/'. Since we add some
# files we want to change to root's home directory.

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

# vi: sts=4 ts=4 sw=4 ai

#apiVersion: kubeadm.k8s.io/v1beta1
#discovery:
#  bootstrapToken:
#    apiServerEndpoint: "10.32.192.46:6443"
#    token: mjmsw8.srj4flh6j5xkyzxz
#    caCertHashes:
#     - "sha256:6c932a865dd420ea08fed258e5f5b918f55ee1c7ca2aa287c9f7cda84071bf97"
#    unsafeSkipCAVerification: false
#  timeout: 5m0s
#kind: JoinConfiguration
#nodeRegistration:
#  criSocket: /var/run/dockershim.sock
#controlPlane:
#  LocalAPIEndpoint:
#    advertiseAddress: 10.32.192.54
##    bindPort: 6443
#
