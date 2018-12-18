#!/bin/bash

###
# A script to create a HA K8S cluster on OpenStack using pure bash and kubeadm
#
# The script is devided into a whole bunch of function, look for the fuction
# called main at the bottom.
#
# The script will create mutliple kubernetes control plane members connected
# via an etcd cluster which is grown in a serial manner. That means we first
# create a single etcd host, and then add N hosts one after another.
#
# The addition of hosts is done via SSH! And that is currently the biggest caveat
# of this script. If one of the hosts will fail to because SSH is still not ready
# the whole cluster will fail to create.
###

set -e

iptables -P FORWARD ACCEPT
swapoff -a

# load koris environment file if available
if [ -f /etc/kubernetes/koris.env ]; then
    source /etc/kubernetes/koris.env
fi

export CURRENT_CLUSTER=""
export CLUSTER_STATE=""


#### Versions for Kube 1.12.3
export KUBE_VERSION=1.12.3
export DOCKER_VERSION=18.06
export CALICO_VERSION=3.3

### Versions for Kube 1.11.5
# export KUBE_VERSION=1.11.5
# export DOCKER_VERSION=17.03
# export CALICO_VERSION=3.1

LOGLEVEL=4
V=${LOGLEVEL}
SSHOPTS="-i /etc/ssh/ssh_host_rsa_key -o StrictHostKeyChecking=no -o ConnectTimeout=60"
################################################################################

# install kubeadm if not already done
sudo apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
sudo apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00

################################################################################

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
bootstrapTokens:
- groups:
  - system:bootstrappers:kubeadm:default-node-token
  token: "\${BOOTSTRAP_TOKEN}"
  ttl: 24h0m0s
  usages:
  - signing
  - authentication
apiServerExtraArgs:
  cloud-provider: openstack
  cloud-config: /etc/kubernetes/cloud.config
controllerManagerExtraArgs:
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
TMPL

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

# write kubelet cloud config for openstack
echo "KUBELET_EXTRA_ARGS=\"--cloud-provider=openstack \
--cloud-config=/etc/kubernetes/cloud.config\"" > /etc/default/kubelet
}

# distributes configuration files and certificates
function distribute_keys() {
   USER=ubuntu # customizable

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
       ssh ${SSHOPTS} ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/cloud.config

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
   kubeadm -v=${V} alpha phase mark-master --config $1
   
   # wait for the API server, we need to do this before installing the addons,
   # otherwise weird timing problems occur irregularly:
   # "error when creating kube-proxy service account: unable to create 
   # serviceaccount: namespaces "kube-system" not found"
   until curl -k --connect-timeout 3  https://${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}/api/v1/nodes/foo;
       do echo "api server is not up! trying again ...";
   done
   
   kubeadm -v=${V} alpha phase addon kube-proxy --config $1
   kubeadm -v=${V} alpha phase addon coredns --config $1
   kubeadm alpha phase bootstrap-token all --config $1

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
   USER=ubuntu # customizable

   echo "*********** Bootstrapping $1 ******************"
   until ssh ${SSHOPTS} ${USER}@$1 hostname; do
       echo "waiting for ssh on $1"
       sleep 2
   done

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
   ssh ${SSHOPTS} ${USER}@$1 sudo kubeadm alpha phase mark-master --config /home/${USER}/kubeadm-$1.yaml
}


function wait_for_etcd () {
    until [[ x"$(kubectl get pod etcd-$1 -n kube-system -o jsonpath='{.status.phase}' 2>/dev/null)" == x"Running" ]]; do
        echo "waiting for etcd-$1 ... "
        sleep 2
    done
}

# the entry point of the whole script.
# this function bootstraps the who etcd cluster and control plane components
# accross N hosts
function main() {
    export first_master=${MASTERS[0]}
    export first_master_ip=${MASTERS_IPS[0]}
    create_config_files
    bootstrap_first_master kubeadm-${first_master}.yaml
    wait_for_etcd ${first_master}

    distribute_keys

    for (( i=1; i<${#MASTERS[@]}; i++ )); do
        echo "bootstrapping master ${MASTERS[$i]}";
        HOST_NAME=${MASTERS[$i]}
        HOST_IP=${MASTERS_IPS[$i]}
        add_master $HOST_NAME $HOST_IP
        wait_for_etcd $HOST_NAME
        echo "done bootstrapping master ${MASTERS[$i]}";
    done

    echo "installing calico"
    # add calico! we should have these manifests in the base image
    # this will prevent failure if there is a network problem
    curl -O https://docs.projectcalico.org/v${CALICO_VERSION}/getting-started/kubernetes/installation/hosted/rbac-kdd.yaml
    curl -O https://docs.projectcalico.org/v${CALICO_VERSION}/getting-started/kubernetes/installation/hosted/kubernetes-datastore/calico-networking/1.7/calico.yaml

    sed -i "s@192.168.0.0/16@"${POD_SUBNET}"@g" calico.yaml

    kubectl apply -f rbac-kdd.yaml
    kubectl apply -f calico.yaml

    echo "done installing calico"
    echo "the installation has finished."
}


# keep this function here, although we don't use it really, it's usefull for
# building bare metal cluster or vSphere clusters
join_all_hosts() {
   export DISCOVERY_HASH=$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | \
       openssl dgst -sha256 -hex | sed 's/^.* //')
   export TOKEN=$(kubeadm token list | grep -v TOK| cut -d" " -f 1 | grep '^\S')

   for K in "${!HOSTS[@]}"; do
       ssh ${K} sudo kubeadm reset -f
       ssh ${K} sudo kubeadm join --token $TOKEN ${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:$LOAD_BALANCER_PORT --discovery-token-ca-cert-hash sha256:${DISCOVERY_HASH}
   done
}


# keep this function here, although we don't use it really, it's usefull for
# building bare metal cluster or vSphere clusters
function fetch_all() {
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    sudo swapoff -a
    curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
    sudo apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
    sudo apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 kubelet=${KUBE_VERSION}-00

    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    sudo apt-get update
    sudo apt-get -y install docker-ce=${DOCKER_VERSION}*
    sudo apt install -y socat conntrack ipset
}


function install_deps() {
    for K in "${ALLHOSTS[@]}"; do
        echo "***** ${K} ******"
        ssh ${K} "KUBE_VERSION=${KUBE_VERSION}; $(typeset -f fetch_all);  fetch_all"
    done
}

# The script is called as user 'root' in the directory '/'. Since we add some
# files we want to change to root's home directory.
cd /root

main
