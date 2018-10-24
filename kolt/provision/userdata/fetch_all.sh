#!/bin/bash
#
# Download all Kubernetes componentes
#
# Don't *yet* use this in the cloud inits
# In the near future our masters will be built at tainted nodes
# then this scrpit will be usefull as cloud-init
# Currently, this script is only for building the base image
###############################################################################
# worker nodes components
###############################################################################

K8S_VERSION=v1.10.4
# Specify the Kubernetes version to use.
# can only use docker 17.03.X
# https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG-1.10.md
DOCKER_VERSION=17.03
OS=linux
ARCH=amd64
CNI_VERSION=0.6.0

# CALICO VERSIONS - edit with care <3 !
calico_version=3.1.3
PODS_SUBNET=10.233.0.0/16

################################################################################
# control plane componentes
################################################################################

CLUSTER_IP_RANGE=10.32.0.0/16
PODS_SUBNET=10.233.0.0/16
# etcd
ETCD_URL=https://github.com/coreos/etcd/releases/download
ETCD_VERSION=v3.3.8

# apiserver, controller-manager, scheduler
K8S_VERSION=v1.10.4
K8S_URL=https://storage.googleapis.com/kubernetes-release/release
BIN_PATH=/usr/bin

#### DON'T CHANGE ANYTHING BELOW ###############################################

# Option strings
function usage(){
	echo >&2 \
	echo "usage: $0 [-f|--fetch]"
	exit 1 ;
}

SHORT="fh"
LONG="fetch,help"

OPTS=`getopt -o $SHORT --long $LONG -n $0 -- "$@" 2>/dev/null`
FETCH_ONLY=0

eval set -- "$OPTS"

while true; do
  case "$1" in
    -h|--help )    usage; shift ;;
    -f|--fetch ) FETCH_ONLY=1; shift;;
    --) shift; break ;;
  esac
done

# check if a binary version is found
# version_check kube-scheduler --version v1.10.4 return 1 if binary is found
# in that version
function version_found() {  return $($1 2>/dev/null $2 | grep -qi $3); }

# download a file and set +x on a file
function curlx() { curl -s -L $1 -o $2 && chmod -v +x $2 ; }

# download a tar ball and extract it to a path
function curl_untar(){
    curl -s -L $1 -O
    tar xavf $2 -C $3
}

export DEBIAN_FRONTEND="noninteractive"

echo "console-setup   console-setup/charmap47 select  UTF-8" > encoding.conf
debconf-set-selections encoding.conf
rm encoding.conf



if [ "$(version_found docker --version ${DOCKER_VERSION}; echo $?)" -eq 1 ]; then
    echo "Docker version did not match"
    apt-get update -y
    apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
    add-apt-repository "deb https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") $(lsb_release -cs) stable" -u


    cat <<EOF > /etc/apt/preferences.d/docker
Package: docker-ce
Pin: version ${DOCKER_VERSION}.*
Pin-Priority: 1000
EOF

   apt-get install -y socat conntrack ipset docker-ce

fi

K8S_URL=https://storage.googleapis.com/kubernetes-release/release
CALICO_URL=https://github.com/projectcalico/cni-plugin/releases/download
BIN_PATH=/usr/bin

for item in kubelet kube-proxy; do
    version_found ${item} --version $K8S_VERSION || curlx ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/${item} ${BIN_PATH}/${item}
done

# configure calico

if [ "$(version_found /opt/cni/bin/calico -v ${calico_version}; echo $?)" -eq 1 ]; then
    mkdir -pv /opt/cni/bin
    mkdir -pv /etc/cni/net.d
    install -v -m 0755 -g root -o root -d /opt/cni/bin/

    cd /tmp

    curl_untar https://github.com/containernetworking/cni/releases/download/v${CNI_VERSION}/cni-plugins-amd64-v{CNI_VERSION}.tgz  cni-plugins-amd64-v{CNI_VERSION}.tgz /opt/cni/bin/

    curlx https://github.com/projectcalico/calicoctl/releases/download/v${calico_version}/calicoctl ${BIN_PATH}/calicoctl

    for item in calico calico-ipam; do
        curlx ${CALICO_URL}/v${calico_version}/${item} /opt/cni/bin/${item}
    done
fi



###################### Do NOT edit anything below ##############################
################################################################################

for item in apiserver controller-manager scheduler; do
    version_found kube-${item} --version $K8S_VERSION || curlx ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kube-${item} ${BIN_PATH}/kube-${item}
done

# etcd
if [ "$(version_found etcd --version ${ETCD_VERSION:1}; echo $?)" -eq 1 ]; then
    echo "etcd version did not match ..."
    cd /tmp
    curl -sL ${ETCD_URL}/${ETCD_VERSION}/etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz -O
    tar -xvf etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz
    cd etcd-${ETCD_VERSION}-${OS}-${ARCH}

    for item in "etcd etcdctl"; do
        install -m 775 ${item} ${BIN_PATH}/
    done
fi

version_found  kubectl "version --client --short" 1.10.4 || curlx ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kubectl ${BIN_PATH}/kubectl

###
# Finished downloading all binaries
###

apt-get update -y && apt-get upgrade -y

# install the latest image
apt install $(apt search linux-image|grep kvm|grep 'linux-image-[0-9]'|tail -1 | cut -d"/" -f1)


###
# install nginx - needed for local proxy
###

apt-get install nginx -y

