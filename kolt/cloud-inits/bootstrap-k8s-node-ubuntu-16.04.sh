text/x-shellscript
#!/bin/sh
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!

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

#### DON'T CHANGE ANYTHING BELOW ===============================================================================

apt-get update
apt-get install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") $(lsb_release -cs) stable" -u


cat <<EOF > /etc/apt/preferences.d/docker
Package: docker-ce
Pin: version ${DOCKER_VERSION}.*
Pin-Priority: 1000
EOF

sudo apt-get -y install socat conntrack ipset docker-ce

K8S_URL=https://storage.googleapis.com/kubernetes-release/release
CALICO_URL=https://github.com/projectcalico/cni-plugin/releases/download
BIN_PATH=/usr/bin

for item in kubelet kube-proxy; do
    curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/${item} -o ${BIN_PATH}/${item}
    chmod -v +x ${BIN_PATH}/${item}
done

# configure calico

cd /tmp
curl -L  https://github.com/containernetworking/plugins/releases/download/v${CNI_VERSION}/cni-plugins-amd64-v${CNI_VERSION}.tgz -O
mkdir -pv /opt/cni/bin
tar xvzf cni-plugins-amd64-v0.6.0.tgz -C /opt/cni/bin/

mkdir -pv /etc/cni/net.d

curl -L https://github.com/projectcalico/calicoctl/releases/download/v${calico_version}/calicoctl -o ${BIN_PATH}/calicoctl && chmod -v +x /usr/bin/calicoctl &


install -v -m 0755 -g root -o root -d /opt/cni/bin/

for item in calico calico-ipam; do
    curl -L ${CALICO_URL}/v${calico_version}/${item} \
        -o /opt/cni/bin/${item} && chmod -v +x /opt/cni/bin/${item} &
done

mkdir -pv /var/lib/kubernetes/

for item in kubernetes-key.pem kubernetes.pem ca.pem; do
    cp -f /etc/ssl/kubernetes/$item /var/lib/kubernetes/$item
done

#ln -vs /etc/ssl/kubernetes/service-accounts.pem /var/lib/kubernetes/service-accounts.pem

cat << EOF > /etc/systemd/system/kubelet.service
[Unit]
Description=Kubernetes Kubelet
Documentation=https://github.com/GoogleCloudPlatform/kubernetes
After=docker.service
Requires=docker.service

[Service]
ExecStart=/usr/bin/kubelet \\
  --allow-privileged=true \\
  --cluster-dns=10.32.0.10  \\
  --hostname-override=$(hostname -s) \\
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
  --v=2

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
ExecStart=/usr/bin/kube-proxy \\
  --kubeconfig=/var/lib/kubelet/kubeconfig.yaml \\
  --proxy-mode=iptables \\
  --iptables-min-sync-period=2s \\
  --iptables-sync-period=5s \\
  --v=2

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo iptables -P FORWARD ACCEPT

sed -i "s/__NODENAME__/"$(hostname -s)"/g"  /etc/cni/net.d/10-calico.conf

sudo systemctl enable kubelet
sudo systemctl start kubelet
sudo systemctl start kube-proxy
sudo systemctl enable kube-proxy
