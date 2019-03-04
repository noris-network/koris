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
#  export B64_CA_CONTENT="$(kubeadm alpha phase certs ca 1>/dev/null 2>&1 && base64 -w 0 /etc/kubernetes/pki/ca.crt)"
#  export LOAD_BALANCER_DNS=""
#  export LOAD_BALANCER_IP=""
#  export LOAD_BALANCER_PORT=""
#  export BOOTSTRAP_TOKEN="$(openssl rand -hex 3).$(openssl rand -hex 8)"
#  export DISCOVERY_HASH="$(openssl x509 -in /etc/kubernetes/pki/ca.crt -noout -pubkey | openssl rsa -pubin -outform DER 2>/dev/null | sha256sum | cut -d' ' -f1)"
#  export MASTERS=( hostname.domain hostname1.domain hostname2.domain ... )
#  export MASTERS_IPS=( 110.234.20.118 10.234.20.119 10.234.20.120 ... )
#  # choose CALICO or FLANNEL
#  export POD_NETWORK="CALICO"
#  export POD_SUBNET="10.233.0.0/16"
#  export SSH_USER="ubuntu"  # for RHEL use root
#
#  # for bare metal or generic images in VMWARE set
#  export BOOTSTRAP_NODES=1
#  # this will install all dependencies on each node
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
LOGLEVEL=4
V=${LOGLEVEL}

SSHOPTS="-i /etc/ssh/ssh_host_rsa_key -o StrictHostKeyChecking=no -o ConnectTimeout=60"

# create a proper kubeadm config file for each master.
# the configuration files are ordered and contain the correct information
# of each master and the rest of the etcd cluster
# WORK: let apiserver know where CA lies
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
  #feature-gates: "PersistentLocalVolumes=False,VolumeScheduling=false"
bootstrapTokens:
- groups:
  - system:bootstrappers:kubeadm:default-node-token
  token: "\${BOOTSTRAP_TOKEN}"
  ttl: 24h0m0s
  usages:
  - signing
  - authentication
controllerManagerExtraArgs:
  cloud-provider: "openstack"
  cloud-config: /etc/kubernetes/cloud.config
  allocate-node-cidrs: "true"
  cluster-cidr: ${POD_SUBNET}
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
    USER=${SSHUSER:-ubuntu}

    echo -n "waiting for ssh on $1"
    until ssh ${SSHOPTS} ${USER}@$1 hostname; do
       echo -n "."
       sleep 1
    done

    echo "distributing keys to $host";
    # clean and recreate directory structure
    ssh ${SSHOPTS} ${USER}@$host sudo rm -vRf /etc/kubernetes
    ssh ${SSHOPTS}  ${USER}@$host mkdir -pv /home/${USER}/kubernetes/pki/etcd
    ssh ${SSHOPTS}  ${USER}@$host mkdir -pv /home/${USER}/kubernetes/manifests

    # copy over everything PKI related, copy to temporary directory with
    # non-root write access
    scp ${SSHOPTS} /etc/kubernetes/pki/ca.crt "${USER}"@$host:/home/${USER}/kubernetes/pki/
    scp ${SSHOPTS} /etc/kubernetes/pki/ca.key "${USER}"@$host:/home/${USER}/kubernetes/pki/
    scp ${SSHOPTS} /etc/kubernetes/pki/sa.key "${USER}"@$host:/home/${USER}/kubernetes/pki/
    scp ${SSHOPTS} /etc/kubernetes/pki/sa.pub "${USER}"@$host:/home/${USER}/kubernetes/pki/
    scp ${SSHOPTS} /etc/kubernetes/pki/front-proxy-ca.crt "${USER}"@$host:/home/${USER}/kubernetes/pki/
    scp ${SSHOPTS} /etc/kubernetes/pki/front-proxy-ca.key "${USER}"@$host:/home/${USER}/kubernetes/pki/
    scp ${SSHOPTS} /etc/kubernetes/pki/etcd/ca.crt "${USER}"@$host:/home/${USER}/kubernetes/pki/etcd/
    scp ${SSHOPTS} /etc/kubernetes/pki/etcd/ca.key "${USER}"@$host:/home/${USER}/kubernetes/pki/etcd/
    scp ${SSHOPTS} /etc/kubernetes/admin.conf "${USER}"@$host:/home/${USER}/kubernetes/
    scp ${SSHOPTS} /etc/kubernetes/cloud.config "${USER}"@$host:/home/${USER}/kubernetes/
    scp ${SSHOPTS} /etc/kubernetes/koris.conf "${USER}"@$host:/home/${USER}/kubernetes/
    scp ${SSHOPTS} /etc/kubernetes/koris.env "${USER}"@$host:/home/${USER}/kubernetes/

    # move back to /etc on remote machine
    ssh ${SSHOPTS} ${USER}@$host sudo mv -v /home/${USER}/kubernetes /etc/
    ssh ${SSHOPTS} ${USER}@$host sudo chown root:root -vR /etc/kubernetes
    ssh ${SSHOPTS} ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/admin.conf

    echo "done distributing keys to $host";
}


# distributes configuration files and certificates
# use this only when all hosts are already up and running
function distribute_keys() {
   USER=${SSHUSER:-ubuntu}

   for (( i=1; i<${#MASTERS_IPS[@]}; i++ )); do
       echo "distributing keys to ${MASTERS_IPS[$i]}";
       host=${MASTERS_IPS[$i]}

       # clean and recreate directory structure
       ssh ${SSHOPTS} ${USER}@$host sudo rm -vRf /etc/kubernetes
       ssh ${SSHOPTS}  ${USER}@$host mkdir -pv /home/${USER}/kubernetes/pki/etcd
       ssh ${SSHOPTS}  ${USER}@$host mkdir -pv /home/${USER}/kubernetes/manifests

       # copy over everything PKI related, copy to temporary directory with
       # non-root write access
       scp ${SSHOPTS} /etc/kubernetes/pki/ca.crt "${USER}"@$host:/home/${USER}/kubernetes/pki/
       scp ${SSHOPTS} /etc/kubernetes/pki/ca.key "${USER}"@$host:/home/${USER}/kubernetes/pki/
       scp ${SSHOPTS} /etc/kubernetes/pki/sa.key "${USER}"@$host:/home/${USER}/kubernetes/pki/
       scp ${SSHOPTS} /etc/kubernetes/pki/sa.pub "${USER}"@$host:/home/${USER}/kubernetes/pki/
       scp ${SSHOPTS} /etc/kubernetes/pki/front-proxy-ca.crt "${USER}"@$host:/home/${USER}/kubernetes/pki/
       scp ${SSHOPTS} /etc/kubernetes/pki/front-proxy-ca.key "${USER}"@$host:/home/${USER}/kubernetes/pki/
       scp ${SSHOPTS} /etc/kubernetes/pki/etcd/ca.crt "${USER}"@$host:/home/${USER}/kubernetes/pki/etcd/
       scp ${SSHOPTS} /etc/kubernetes/pki/etcd/ca.key "${USER}"@$host:/home/${USER}/kubernetes/pki/etcd/
       scp ${SSHOPTS} /etc/kubernetes/admin.conf "${USER}"@$host:/home/${USER}/kubernetes/
       scp ${SSHOPTS} /etc/kubernetes/cloud.config "${USER}"@$host:/home/${USER}/kubernetes/
       scp ${SSHOPTS} /etc/kubernetes/koris.conf "${USER}"@$host:/home/${USER}/kubernetes/
       scp ${SSHOPTS} /etc/kubernetes/koris.env "${USER}"@$host:/home/${USER}/kubernetes/

       # move back to /etc on remote machine
       ssh ${SSHOPTS} ${USER}@$host sudo mv -v /home/${USER}/kubernetes /etc/
       ssh ${SSHOPTS} ${USER}@$host sudo chown root:root -vR /etc/kubernetes
       ssh ${SSHOPTS} ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/admin.conf

       echo "done distributing keys to ${MASTERS_IPS[$i]}";
   done
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
    USER=${SSHUSER:-ubuntu}

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
    ssh ${1} "KUBE_VERSION=${KUBE_VERSION}; $(
    typeset -f get_docker_ubuntu;
    typeset -f get_docker_centos;
    typeset -f get_kubeadm_ubuntu;
    typeset -f get_kubeadm_centos;
    typeset -f get_docker;
    typeset -f get_kubeadm;
    typeset -f fetch_all);
    sudo iptables -P FORWARD ACCEPT;
    sudo swapoff -a;
    sudo fetch_all;"
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
        done

        wait_for_etcd $HOST_NAME
        echo "done bootstrapping master ${MASTERS[$i]}";
    done

    if [ $1 == "--join-all-nodes" ]; then
        HOSTS=${K8SNODES:?"You must define K8SNODES"}
        join_all_hosts --install-deps
    fi

    echo "the installation has finished."
}


# when building bare metal cluster or vSphere clusters this is used to
# install dependencies on each host and join the host to the cluster
join_all_hosts() {
    if [ -z ${DISCOVERY_HASH} ]; then
        export DISCOVERY_HASH=$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
                                openssl rsa -pubin -outform der 2>/dev/null | \
                                openssl dgst -sha256 -hex | sed 's/^.* //')
   fi
   if [ -z ${BOOTSTRAP_TOKEN} ]; then
        export TOKEN=$(kubeadm token list | grep -v TOK| cut -d" " -f 1 | grep '^\S')
   fi
   for K in "${!HOSTS[@]}"; do
       echo "***** ${K} ******"
       if [ $1 == "--install-deps" || -n ${BOOTSTRAP_NODES} ]; then
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
    main
    cd /root
fi

# vi: expandtab ts=4 sw=4 ai
