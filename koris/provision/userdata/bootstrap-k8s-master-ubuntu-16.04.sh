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
#
# Future work: add a mechanism to recover from ssh failure.
##

set -e

# all the variables here should be writen to /etc/kubernetes/koris.env
# via cloud_init.py

declare -A MASTERS
declare -A HOSTS
MASTERS["master-1-a"]="de-nbg6-1a"
MASTERS["master-2-a"]="de-nbg6-1a"
MASTERS["master-3-b"]="de-nbg6-1b"
HOSTS["worker-1-a"]="de-nbg6-1a"
HOSTS["worker-2-a"]="de-nbg6-1a"
HOSTS["worker-3-a"]="de-nbg6-1a"
HOSTS["worker-4-b"]="de-nbg6-1b"
HOSTS["worker-5-b"]="de-nbg6-1b"
HOSTS["worker-6-b"]="de-nbg6-1b"
export HOSTS
export SUBNET="k8s-subnet"
export FLOATING_IP="213.95.155.150"
export LOAD_BALANCER_IP=213.95.155.150
export LOAD_BALANCER_PORT=6443
export POD_SUBNET=10.233.0.0/16
export KUBE_VERSION=1.11.4

MASTERS_IPS=( 192.168.0.121 192.168.0.126 192.168.0.123 )
MASTERS=( master-1-a master-2-a master-3-b )

export ALLHOSTS=( "${!HOSTS[@]}" "${!MASTERS[@]}" )
export CURRENT_CLUSTER=""


#### Versions for Kube 1.12.2
KUBE_VERSION=1.12.2
DOCKER_VERSION=18.06
CALICO_VERSION=3.3

### Versions for Kube 1.11.4
#KUBE_VERSION=1.11.5
#DOCKER_VERSION=17.03
#CALICO_VERSION=3.1

LOGLEVEL=4
################################################################################

# writes /etc/kubernetes/cloud.config
# we can throw this away once cloud_init.py is working again
function write_cloud_conf() {

PY_CODE=$(cat <<END
# This works only with
# pip3 install openstacksdk==0.12.0

from openstack.config.loader import _get_os_environ

def env_to_cloud_conf(os_env_dict):
    d = {}
    d['domain-name'] = os_env_dict['user_domain_name']
    d['region'] = os_env_dict['region_name']
    d['tenant-id'] = os_env_dict['project_id']
    d['auth-url'] = os_env_dict['auth_url']
    d['password'] = os_env_dict['password']
    d['username'] = os_env_dict['username']
    return d

with open("cloud.config", "w") as conf:
    conf.write("[Global]\n" + "\n".join(
        "%s=%s" % (k, v) for (k, v) in env_to_cloud_conf(
            _get_os_environ("OS_")).items()))
END
)

python3 -c "$PY_CODE"
install -m 600 cloud.config /etc/kubernetes/cloud.config
}

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
    serverCertSANs:
      - \${HOST_NAME}
      - \${HOST_IP}
    peerCertSANs:
      - \${HOST_NAME}
      - \${HOST_NAME}
networking:
    # This CIDR is a Calico default. Substitute or remove for your CNI provider.
    podSubnet: \${POD_SUBNET}
nodeRegistrationOptions:
  kubeletExtraArgs:
    cloud-provider: openstack
    cloud-config: etc/kubernetes/cloud.config
bootstrapTokens:
- groups:
  - system:bootstrappers:kubeadm:default-node-token
  token: foobar.fedcba9876543210
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
- name: "/etc/kubernetes/cloud.config"
  hostPath: "/etc/kubernetes/cloud.config"
  mountPath: "/etc/kubernetes/cloud.config"
  writable: false
  pathType: File
controllerManagerExtraVolumes:
- name: "/etc/kubernetes/cloud.config"
  hostPath: "/etc/kubernetes/cloud.config"
  mountPath: "/etc/kubernetes/cloud.config"
  writable: false
  pathType: File
TMPL

for i in ${!MASTERS[@]}; do
	echo $i, ${MASTERS[$i]}, ${MASTERS_IPS[$i]}
	export HOST_IP="${MASTERS_IPS[$i]}"
	export HOST_NAME="${MASTERS[$i]}"
	CURRENT_CLUSTER="${CURRENT_CLUSTER}$HOST_NAME=https://${HOST_IP}:2380,"
        CURRENT_CLUSTER=${CURRENT_CLUSTER%?}
	envsubst  < init.tmpl > kubeadm-${HOST_NAME}.yaml
done
}

# distributes configuration files and certificates
function distribute_keys() {
   USER=ubuntu # customizable
   for host in ${CONTROL_PLANE_IPS}; do
       ssh -i /home/ubuntu/.ssh/id_rsa ${USER}@$host sudo rm -vRf /etc/kubernetes
       ssh -i /home/ubuntu/.ssh/id_rsa  ${USER}@$host mkdir -pv kubernetes/pki/etcd
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/ca.crt "${USER}"@$host:~/kubernetes/pki/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/ca.key "${USER}"@$host:~/kubernetes/pki/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/sa.key "${USER}"@$host:~/kubernetes/pki/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/sa.pub "${USER}"@$host:~/kubernetes/pki/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/front-proxy-ca.crt "${USER}"@$host:~/kubernetes/pki/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/front-proxy-ca.key "${USER}"@$host:~/kubernetes/pki/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/etcd/ca.crt "${USER}"@$host:~/kubernetes/pki/etcd/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/pki/etcd/ca.key "${USER}"@$host:~/kubernetes/pki/etcd/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/admin.conf "${USER}"@$host:~/kubernetes/
       sudo -E scp -i /home/ubuntu/.ssh/id_rsa /etc/kubernetes/cloud.config "${USER}"@$host:~/kubernetes/

       ssh -i /home/ubuntu/.ssh/id_rsa ${USER}@$host sudo mv -v kubernetes /etc/
       ssh -i /home/ubuntu/.ssh/id_rsa ${USER}@$host sudo chown root:root -vR /etc/kubernetes
       ssh -i /home/ubuntu/.ssh/id_rsa ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/admin.conf
       ssh -i /home/ubuntu/.ssh/id_rsa ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/cloud.config
   done
}


V=${LOGLEVEL}

# bootstrap the first master.
# the process is slightly different then for the rest of the N masters
# we add
function bootstrap_first_master() {
   echo "*********** Bootstrapping master-1 ******************"
   kubeadm -v=${V} alpha phase certs all --config $1
   kubeadm -v=${V} alpha phase kubelet config write-to-disk --config $1
   kubeadm -v=${V} alpha phase kubelet write-env-file --config $1
   kubeadm -v=${V} alpha phase kubeconfig kubelet --config $1
   kubeadm -v=${V} alpha phase kubeconfig all --config $1
   distribute_keys
   systemctl start kubelet
   kubeadm -v=${V} alpha phase etcd local --config $1
   kubeadm -v=${V} alpha phase controlplane all --config $1
   kubeadm -v=${V} alpha phase mark-master --config $1
   kubeadm -v=${V} alpha phase addon kube-proxy --config $1
   kubeadm -v=${V} alpha phase addon coredns --config $1
   kubeadm alpha phase bootstrap-token all --config $1
   test -d .kube || mkdir .kube
   sudo cp /etc/kubernetes/admin.conf ~/.kube/config
   chown ubuntu:ubuntu ~/.kube/config
   # this only works if the api is available
   until curl -k --connect-timeout 3  https://${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}/api/v1/nodes/foo;
       do echo "api server is not up! trying again ...";
   done
   kubeadm -v=${V} alpha phase kubelet config upload  --config $1
   kubeadm token create --config $1
   kubectl get nodes
}

# add a master to the cluster
# the first argument is the host name to add
# the second argument is the host IP
function add_master {
   echo "*********** Bootstrapping $1 ******************"
   scp -i /home/ubuntu/.ssh/id_rsa kubeadm-$1.yaml ubuntu@$1:~/
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase certs all --config  kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase kubelet config write-to-disk --config  kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase kubelet write-env-file --config  kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase kubeconfig kubelet --config  kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo systemctl start kubelet
   # join the etcd host to the cluster
   sudo kubectl exec -n kube-system etcd-${first_master} -- etcdctl --ca-file /etc/kubernetes/pki/etcd/ca.crt --cert-file /etc/kubernetes/pki/etcd/peer.crt --key-file /etc/kubernetes/pki/etcd/peer.key --endpoints=https://${first_master_ip}:2379 member add $1 https://$2:2380
   # launch etcd
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase etcd local --config  kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase kubeconfig all --config  kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase controlplane all --config   kubeadm-$1.yaml
   ssh -i /home/ubuntu/.ssh/id_rsa ubuntu@$1 sudo kubeadm alpha phase mark-master --config  kubeadm-master-$1.yaml
}


function wait_for_etcd () {
    until [[ x"$(kubectl get pod etcd-$1 -n kube-system -o jsonpath='{.status.phase}' 2>/dev/null)" == x"Running" ]]; do
        echo "waiting for etcd-$1 ... "
        sleep 2
    done
}

# the entry point of the who script.
# this function bootstraps the who etcd cluster and control plane components
# accross N hosts
function main() {
    export first_master=${MASTERS[0]}
    export first_master_ip=${MASTERS_IPS[0]}
    create_config_files
    write_cloud_conf
    bootstrap_first_master kubeadm-master-1.yaml
    wait_for_etcd master-1-a

    for (( i=1; i<${#MASTERS[@]}; i++ )); do
        echo "${MASTERS[$i]}";
        HOST_NAME=${MASTERS[$i]}
        HOST_IP=${MASTERS_IPS[$i]}
        add_master $HOST_NAME $HOST_IP
        wait_for_etcd $HOST_NAME
    done

    # add calico! we should have these manifests in the base image
    # this will prevent failure if there is a network problem
    curl -O https://docs.projectcalico.org/v${CALICO_VERSION}/getting-started/kubernetes/installation/hosted/rbac-kdd.yaml
    curl -O https://docs.projectcalico.org/v${CALICO_VERSION}/getting-started/kubernetes/installation/hosted/kubernetes-datastore/calico-networking/1.7/calico.yaml

    sed -i "s@192.168.0.0/16@"${POD_SUBNET}"@g" calico.yaml

    kubectl apply -f rbac-kdd.yaml
    kubectl apply -f calico.yaml
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


main
