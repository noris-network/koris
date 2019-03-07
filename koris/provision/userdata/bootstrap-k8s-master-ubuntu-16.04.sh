#!/bin/bash

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
#       export K8SNODES=( node-1 node-2 ) # a list of nodes to join
#
###

# load koris environment file if available
if [ -f /etc/kubernetes/koris.env ]; then
    source /etc/kubernetes/koris.env
fi

export CURRENT_CLUSTER=""
export CLUSTER_STATE=""


#### Versions for Kube 1.12.3
export KUBE_VERSION=1.12.5
export DOCKER_VERSION=18.06
export CALICO_VERSION=3.3
export POD_SUBNET=${POD_SUBNET:-"10.233.0.0/16"}
export SSH_USER=${SSH_USER:-"ubuntu"}
export BOOTSTRAP_NODES=${BOOTSTRAP_NODES:-0}
export OPENSTACK=${OPENSTACK:-1}
export K8SNODES=${K8SNODES:-""}
LOGLEVEL=4
V=${LOGLEVEL}

SSHOPTS="-i /etc/ssh/ssh_host_rsa_key -o StrictHostKeyChecking=no -o ConnectTimeout=60"

# create a proper kubeadm config file for each master.
# the configuration files are ordered and contain the correct information
# of each master and the rest of the etcd cluster
function create_config_files() {
    cat <<TMPL > init.tmpl
apiVersion: kubeadm.k8s.io/v1alpha2
kind: MasterConfiguration
kubernetesVersion: v${KUBE_VERSION}
apiServerCertSANs:
- "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}"
api:
    controlPlaneEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
etcd:
  local:
    extraArgs:
      listen-client-urls: "https://127.0.0.1:2379,https://\${HOST_IP}:2379"
      advertise-client-urls: "https://\${HOST_IP}:2379"
      listen-peer-urls: "https://\${HOST_IP}:2380"
      initial-advertise-peer-urls: "https://\${HOST_IP}:2380"
      initial-cluster: "\${CURRENT_CLUSTER}"
      initial-cluster-state: "\${CLUSTER_STATE}"
    serverCertSANs:
      - \${HOST_NAME}
      - \${HOST_IP}
    peerCertSANs:
      - \${HOST_NAME}
      - \${HOST_IP}
networking:
    # This CIDR is a Calico default. Substitute or remove for your CNI provider.
    podSubnet: \${POD_SUBNET}
#apiServerExtraArgs:
#  allow-privileged: "true"
#  enable-admission-plugins: "Initializers,NamespaceLifecycle,LimitRanger,ServiceAccount,DefaultStorageClass,MutatingAdmissionWebhook,ValidatingAdmissionWebhook,ResourceQuota"
#  feature-gates: "PersistentLocalVolumes=False,VolumeScheduling=false"
bootstrapTokens:
- groups:
  - system:bootstrappers:kubeadm:default-node-token
  token: "\${BOOTSTRAP_TOKEN}"
  ttl: 24h0m0s
  usages:
  - signing
  - authentication
controllerManagerExtraArgs:
  allocate-node-cidrs: "true"
  cluster-cidr: ${POD_SUBNET}
TMPL
# if On baremetal we don't need all OpenStack cloud provider flags
if [[ OPENSTACK -eq 1 ]]; then
cat <<TMPL > init.tmpl
  cloud-provider: "openstack"
  cloud-config: /etc/kubernetes/cloud.config
apiServerExtraVolumes:
- name: "cloud-config"
  hostPath: "/etc/kubernetes/cloud.config"
  mountPath: "/etc/kubernetes/cloud.config"
  writable: false
  pathType: File
controllerManagerExtraVolumes:
- name: "cloud-config"
  hostPath: "/etc/kubernetes/cloud.config"
  mountPath: "/etc/kubernetes/cloud.config"
  writable: false
  pathType: File
apiServerExtraArgs:
  cloud-provider: openstack
  cloud-config: /etc/kubernetes/cloud.config
TMPL
fi

# If Dex is to be deployed, we need to start the apiserver with extra args.
if [[ -n ${OIDC_CLIENT_ID+x} ]]; then
cat <<TMPL > dex.tmpl
  oidc-issuer-url: "${OIDC_ISSUER_URL}"
  oidc-client-id: ${OIDC_CLIENT_ID}
  oidc-ca-file: ${OIDC_CA_FILE}
  oidc-username-claim: ${OIDC_USERNAME_CLAIM}
  oidc-groups-claim: ${OIDC_GROUPS_CLAIM}
TMPL
    cat dex.tmpl >> init.tmpl
fi

    for i in ${!MASTERS[@]}; do
        echo $i, ${MASTERS[$i]}, ${MASTERS_IPS[$i]}
        export HOST_IP="${MASTERS_IPS[$i]}"
        export HOST_NAME="${MASTERS[$i]}"
    if [ -z "$CURRENT_CLUSTER" ]; then
        CLUSTER_STATE="new"
        CURRENT_CLUSTER="$HOST_NAME=https://${HOST_IP}:2380"
    else
        CLUSTER_STATE="existing"
        CURRENT_CLUSTER="${CURRENT_CLUSTER},$HOST_NAME=https://${HOST_IP}:2380"
    fi

        envsubst  < init.tmpl > kubeadm-${HOST_NAME}.yaml
    done

}

# distributes configuration file and certificates to a master node
function copy_keys() {
    host=$1
    USER=${SSH_USER:-ubuntu}

    echo -n "waiting for ssh on $1"
    until ssh ${SSHOPTS} ${USER}@$1 hostname; do
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
    sftp ${USER}@$host << EOF
	put /etc/kubernetes/pki/ca.crt /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/ca.key /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/sa.key /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/sa.pub /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/front-proxy-ca.crt /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/front-proxy-ca.key /home/${USER}/kubernetes/pki/
	put /etc/kubernetes/pki/etcd/ca.crt /home/${USER}/kubernetes/pki/etcd/
	put /etc/kubernetes/pki/etcd/ca.key /home/${USER}/kubernetes/pki/etcd/
	put /etc/kubernetes/admin.conf /home/${USER}/kubernetes/
	put /etc/kubernetes/koris.env /home/${USER}/kubernetes/
EOF

   # move back to /etc on remote machine
   ssh ${SSHOPTS} ${USER}@$host sudo mv -v /home/${USER}/kubernetes /etc/
   ssh ${SSHOPTS} ${USER}@$host sudo chown root:root -vR /etc/kubernetes
   ssh ${SSHOPTS} ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/admin.conf

   echo "done distributing keys to $host";
}


# bootstrap the first master.
# the process is slightly different than for the rest of the N masters
# we add
function bootstrap_first_master() {
   echo "*********** Bootstrapping master-1 ******************"
   kubeadm -v=${V} alpha phase certs all --config $1
   kubeadm -v=${V} alpha phase kubelet config write-to-disk --config $1
   kubeadm -v=${V} alpha phase kubelet write-env-file --config $1
   kubeadm -v=${V} alpha phase kubeconfig kubelet --config $1
   kubeadm -v=${V} alpha phase kubeconfig all --config $1
   systemctl start kubelet
   kubeadm -v=${V} alpha phase etcd local --config $1
   kubeadm -v=${V} alpha phase controlplane all --config $1
   until kubeadm -v=${V} alpha phase mark-master --config $1; do
       sleep 1
   done

   # wait for the API server, we need to do this before installing the addons,
   # otherwise weird timing problems occur irregularly:
   # "error when creating kube-proxy service account: unable to create
   # serviceaccount: namespaces "kube-system" not found"
   until curl -k --connect-timeout 3  https://${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}/api/v1/nodes/foo;
       do echo "api server is not up! trying again ...";
   done

   until kubeadm -v=${V} alpha phase addon kube-proxy --config $1; do
       sleep 1
   done
   until kubeadm -v=${V} alpha phase addon coredns --config $1; do
       sleep 1
   done
   until kubeadm alpha phase bootstrap-token all --config $1; do
       sleep 1
   done
   test -d /root/.kube || mkdir -p /root/.kube
   cp /etc/kubernetes/admin.conf /root/.kube/config
   chown root:root /root/.kube/config

   kubeadm -v=${V} alpha phase kubelet config upload  --config $1
   kubectl get nodes
}

# add a master to the cluster
# the first argument is the host name to add
# the second argument is the host IP
function add_master {
    USER=${SSH_USER:-ubuntu}

   echo "*********** Bootstrapping $1 ******************"
   until ssh ${SSHOPTS} ${USER}@$1 hostname; do
       echo "waiting for ssh on $1"
       sleep 2
   done
   if [ ${BOOTSTRAP_NODES} -eq 1 ]; then
        bootstrap_deps_node $1
   fi

   scp ${SSHOPTS} kubeadm-$1.yaml ${USER}@$1:/home/${USER}

   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase certs all --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase kubelet config write-to-disk --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase kubelet write-env-file --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase kubeconfig kubelet --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 sudo systemctl start kubelet

   # join the etcd host to the cluster, this is executed on local node!
   kubectl exec -n kube-system etcd-${first_master} -- etcdctl --ca-file /etc/kubernetes/pki/etcd/ca.crt --cert-file /etc/kubernetes/pki/etcd/peer.crt --key-file /etc/kubernetes/pki/etcd/peer.key --endpoints=https://${first_master_ip}:2379 member add $1 https://$2:2380

   # launch etcd
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase etcd local --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase kubeconfig all --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase controlplane all --config /home/${USER}/kubeadm-$1.yaml
   ssh ${SSHOPTS} ${USER}@$1 "until sudo kubeadm alpha phase mark-master --config /home/${USER}/kubeadm-$1.yaml; do sleep 1; done"
}


function wait_for_etcd () {
    until [[ x"$(kubectl get pod etcd-$1 -n kube-system -o jsonpath='{.status.phase}' 2>/dev/null)" == x"Running" ]]; do
        echo "waiting for etcd-$1 ... "
        sleep 2
    done
}


TRANSPORT_PACKAGES="apt-transport-https ca-certificates software-properties-common"

# fetch and prepare calico manifests
function get_calico(){
    while [ ! -f rbac-kdd.yaml ]; do
        curl --retry 10 -sfLO https://docs.projectcalico.org/v${CALICO_VERSION}/getting-started/kubernetes/installation/hosted/rbac-kdd.yaml
    done
    while [ ! -f calico.yaml ]; do
        curl --retry 10 -sfLO https://docs.projectcalico.org/v${CALICO_VERSION}/getting-started/kubernetes/installation/hosted/kubernetes-datastore/calico-networking/1.7/calico.yaml
    done

    sed -i "s@192.168.0.0/16@"${POD_SUBNET}"@g" calico.yaml
}


# fetch the manifest for flannel
function get_flannel(){
    while [ ! -r kube-flannel.yml ]; do
         curl --retry 10 -sfLO https://raw.githubusercontent.com/coreos/flannel/bc79dd1505b0c8681ece4de4c0d86c5cd2643275/Documentation/kube-flannel.yml
    done
    sed -i "s@\"Type\": \"vxlan\"@\"Type\": \"ipip\"@g" kube-flannel.yml
    sed -i "s@10.244.0.0/16@"${POD_SUBNET}"@g" kube-flannel.yml
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
            kubectl apply -f rbac-kdd.yaml
            kubectl apply -f calico.yaml
            ;;
        "FLANNEL")
            echo "installing flannel"
            kubectl apply -f kube-flannel.yml
            ;;
    esac
}

# get docker version for CentOS
function get_docker_centos() {
    yum install -y yum-utils \
        device-mapper-persistent-data \
        lvm2
    yum-config-manager \
    --add-repo \
    https://download.docker.com/linux/centos/docker-ce.repo
    # docker-ce docker-ce-cli
    yum install -y 'docker-ce-'${DOCKER_VERSION}'*' containerd.io
    systemctl enable docker
    systemctl start docker
}

# get kubeadm version for CentOS
function get_kubeadm_centos() {
    cat <<EOF > /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://packages.cloud.google.com/yum/repos/kubernetes-el7-x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://packages.cloud.google.com/yum/doc/yum-key.gpg https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
exclude=kube*
EOF

    # Set SELinux in permissive mode (effectively disabling it)
    setenforce 0
    sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config

    yum install -y kubelet-${KUBE_VERSION} kubeadm-${KUBE_VERSION} kubectl-${KUBE_VERSION} --disableexcludes=kubernetes
    systemctl enable --now kubelet

    cat <<EOF >  /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
EOF
sysctl --system
}

function bootstrap_deps_node() {
ssh ${SSHOPTS} ${SSH_USER}@${1} sudo bash << EOF
set -ex;
iptables -P FORWARD ACCEPT;
swapoff -a;
KUBE_VERSION=${KUBE_VERSION};
DOCKER_VERSION=${DOCKER_VERSION};
first_master=${first_master}
$(typeset -f get_docker_ubuntu);
$(typeset -f get_docker_centos);
$(typeset -f get_kubeadm_ubuntu);
$(typeset -f get_kubeadm_centos);
$(typeset -f get_docker);
$(typeset -f get_kubeadm);
$(typeset -f fetch_all);
fetch_all;
EOF
}

# enforce docker version
function get_docker_ubuntu() {
    dpkg -l software-properties-common | grep ^ii || sudo apt install $TRANSPORT_PACKAGES -y
    curl --retry 10 -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    apt-get update
    apt-get -y install docker-ce="${DOCKER_VERSION}*"
    apt install -y socat conntrack ipset
}

# enforce kubeadm version
function get_kubeadm_ubuntu() {
    dpkg -l software-properties-common | grep ^ii || sudo apt install $TRANSPORT_PACKAGES -y
    curl --retry 10 -fssL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00
}

function get_docker(){
    if [ -z $(which apt) ]; then
        get_docker_centos;
    else
        get_docker_ubuntu;
    fi
}

function get_kubeadm(){
    if [ -z $(which apt) ]; then
        get_kubeadm_centos;
    else
        get_kubeadm_ubuntu;
    fi
}

# the entry point of the whole script.
# this function bootstraps the who etcd cluster and control plane components
# accross N hosts
function main() {
    get_net_plugin &
    pid_get_net_plugin=$!

    get_docker
    get_kubeadm &
    pid_get_kubeadm=$!

    export first_master=${MASTERS[0]}
    export first_master_ip=${MASTERS_IPS[0]}
    create_config_files

    wait $pid_get_kubeadm

    bootstrap_first_master kubeadm-${first_master}.yaml
    wait_for_etcd ${first_master}

    wait $pid_get_net_plugin
    apply_net_plugin

    for (( i=1; i<${#MASTERS[@]}; i++ )); do
        echo "bootstrapping master ${MASTERS[$i]}";
        HOST_NAME=${MASTERS[$i]}
        HOST_IP=${MASTERS_IPS[$i]}
        copy_keys $HOST_IP
        until add_master $HOST_NAME $HOST_IP; do
            ssh $HOST_NAME sudo kubeadm reset -f
            copy_keys $HOST_IP
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
join_all_hosts() {
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
    get_docker
    get_kubeadm
}

# The script is called as user 'root' in the directory '/'. Since we add some
# files we want to change to root's home directory.

# This line and the if condition bellow allow sourcing the script without executing
# the main function
(return 0 2>/dev/null) && sourced=1 || sourced=0

if [[ $sourced == 1 ]]; then
    echo "You can now use any of these functions:"
    echo ""
    typeset -F |  cut -d" " -f 3
else
    set -eu
    cd /root
    iptables -P FORWARD ACCEPT
    swapoff -a
    main $@
fi

# vi: expandtab ts=4 sw=4 ai
