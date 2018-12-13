text/x-shellscript
#!/bin/bash
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!

K8S_VERSION=v1.11.5
# Specify the Kubernetes version to use.
# can only use docker 17.03.X
# https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG-1.10.md
DOCKER_VERSION=17.12
OS=linux
ARCH=amd64
CNI_VERSION=0.6.0

# CALICO VERSIONS - edit with care <3 !
calico_version=3.1.3

PODS_SUBNET=10.233.0.0/16
#### DON'T CHANGE ANYTHING BELOW ===============================================================================


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
function version_found() {  return $($1 $2 2>/dev/null | grep -qi $3); }

# download a file and set +x on a file
function curlx() { curl -s $1 -o $2 && chmod -v +x $2 ; }

export DEBCONF_FRONTEND=noninteractive

echo "console-setup   console-setup/charmap47 select  UTF-8" > encoding.conf
debconf-set-selections encoding.conf
rm encoding.conf

apt-get -qy update && apt-get -qy -o "Dpkg::Options::=--force-confdef" -o "Dpkg::Options::=--force-confold" upgrade &&  apt-get -qy autoclean

if [ "$(version_found docker --version ${DOCKER_VERSION}; echo $?)" -eq 1 ]; then
    echo "Docker version did not match"
    apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
    add-apt-repository "deb https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") $(lsb_release -cs) stable" -u
    apt-get -qy update

    cat <<EOF > /etc/apt/preferences.d/docker
Package: docker-ce
Pin: version ${DOCKER_VERSION}.*
Pin-Priority: 1000
EOF

    apt-get -y install socat conntrack ipset docker-ce

fi

K8S_URL=https://storage.googleapis.com/kubernetes-release/release
CALICO_URL=https://github.com/projectcalico/cni-plugin/releases/download
BIN_PATH=/usr/bin

for item in kubelet kube-proxy; do
    version_found ${item} --version $K8S_VERSION || curlx ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/${item} ${BIN_PATH}/${item}
done

# configure calico

if [ "$(version_found /opt/cni/bin/calico -v ${calico_version}; echo $?)" -eq 1 ]; then
    cd /tmp
    curl -s -L  https://github.com/containernetworking/plugins/releases/download/v${CNI_VERSION}/cni-plugins-amd64-v${CNI_VERSION}.tgz -O
    mkdir -pv /opt/cni/bin
    tar xvzf cni-plugins-amd64-v0.6.0.tgz -C /opt/cni/bin/
    mkdir -pv /etc/cni/net.d

    curl -s -L https://github.com/projectcalico/calicoctl/releases/download/v${calico_version}/calicoctl -o ${BIN_PATH}/calicoctl && chmod -v +x /usr/bin/calicoctl &

    install -v -m 0755 -g root -o root -d /opt/cni/bin/

    for item in calico calico-ipam; do
        curl -s -L ${CALICO_URL}/v${calico_version}/${item} \
             -o /opt/cni/bin/${item} && chmod -v +x /opt/cni/bin/${item} &
    done

fi

###
# Finished downloading all binaries
###
if [ ${FETCH_ONLY} -eq 1 ]; then
    echo "finished downloading all binaries"
    exit 0
fi

echo "testing if /var/lib/kubernetes/ exists"
test -d /var/lib/kubernetes || mkdir -pv $_

for item in kubernetes-key.pem kubernetes.pem ca.pem; do
    test -r /etc/ssl/kubernetes/$item && cp -f /etc/ssl/kubernetes/$item /var/lib/kubernetes/$item
done

cat << EOF > /etc/systemd/system/kubelet.service
[Unit]
Description=Kubernetes Kubelet
Documentation=https://github.com/GoogleCloudPlatform/kubernetes
After=docker.service
Requires=docker.service

[Service]
EnvironmentFile=/etc/systemd/system/kubelet.env
ExecStart=/usr/bin/kubelet \\
  --allow-privileged=true \\
  --cluster-dns=10.32.0.10  \\
  --cni-bin-dir=/opt/cni/bin \\
  --hostname-override=$(hostname -s) \\
  --cloud-provider=openstack \\
  --cloud-config=/etc/kubernetes/cloud.conf \\
  --container-runtime=docker \\
  --docker=unix:///var/run/docker.sock \\
  --network-plugin=cni \\
  --kubeconfig=/var/lib/kubelet/kubeconfig.yaml \\
  --runtime-cgroups=/systemd/system.slice \\
  --kubelet-cgroups=/systemd/system.slice \\
  --serialize-image-pulls=false \\
  --register-node=true \\
  --tls-cert-file=/var/lib/kubernetes/kubernetes.pem \\
  --tls-private-key-file=/var/lib/kubernetes/kubernetes-key.pem \\
  --eviction-pressure-transition-period 30s \\
  --cert-dir=/var/lib/kubelet \\
  --cluster-domain=cluster.local \\
  --v=2 \\
  --node-ip=\${NODE_IP}

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat << EOF > /etc/systemd/system/kube-proxy.service
[Unit]
Description=Kubernetes Kube Proxy
Documentation=https://github.com/GoogleCloudPlatform/kubernetes

[Service]
EnvironmentFile=/etc/systemd/system/kube-proxy.env
ExecStart=/usr/bin/kube-proxy \\
  --kubeconfig=/var/lib/kubelet/kubeconfig.yaml \\
  --proxy-mode=iptables \\
  --iptables-min-sync-period=2s \\
  --iptables-sync-period=5s \\
  --cluster-cidr=${PODS_SUBNET} \\
  --master=https://\${LB_IP}:6443
  --v=2

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

iptables -P FORWARD ACCEPT

systemctl enable kubelet
systemctl start kubelet
systemctl start kube-proxy
systemctl enable kube-proxy
