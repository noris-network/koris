text/x-shellscript
#!/bin/bash
# bootstrap k8s master without kubeadm / kubespray

#################### project sources and settings ##############################
################################################################################

OS=linux
ARCH=amd64
CLUSTER_IP_RANGE=10.32.0.0/16
PODS_SUBNET=10.233.0.0/16
# etcd
ETCD_URL=https://github.com/coreos/etcd/releases/download
ETCD_VERSION=v3.3.8

# apiserver, controller-manager, scheduler
K8S_VERSION=v1.10.4
K8S_URL=https://storage.googleapis.com/kubernetes-release/release
BIN_PATH=/usr/bin

###################### Do NOT edit anything below ##############################
################################################################################

CURRENT_IP=$(curl http://169.254.169.254/latest/meta-data/local-ipv4)
HOST_NAME=$(hostname)

# download and setup daemons ###################################################


for item in apiserver controller-manager scheduler; do
    curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kube-${item} -o ${BIN_PATH}/kube-${item} && \
    chmod -v +x ${BIN_PATH}/kube-${item} &
done

# etcd

cd /tmp
curl -L ${ETCD_URL}/${ETCD_VERSION}/etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz -O
tar -xvf etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz
cd etcd-${ETCD_VERSION}-${OS}-${ARCH}

for item in "etcd etcdctl"; do
  install -m 775 ${item} ${BIN_PATH}/
done

sudo apt-get update && apt-get ugrade -y

cat << EOF > /etc/systemd/system/etcd.service
[Unit]
Description=etcd
Documentation=https://github.com/coreos

[Service]
EnvironmentFile=/etc/systemd/system/etcd.env
ExecStart=/usr/bin/etcd --name=${HOSTNAME} \\
        --data-dir=/var/lib/etcd \\
        --cert-file=/etc/ssl/kubernetes/kubernetes.pem \\
        --key-file=/etc/ssl/kubernetes/kubernetes-key.pem \\
        --peer-cert-file=/etc/ssl/kubernetes/kubernetes.pem \\
        --peer-key-file=/etc/ssl/kubernetes/kubernetes-key.pem  \\
        --trusted-ca-file=/etc/ssl/kubernetes/ca.pem \\
        --peer-trusted-ca-file=/etc/ssl/kubernetes/ca.pem \\
        --listen-client-urls https://${CURRENT_IP}:2379,http://127.0.0.1:2379 \\
        --advertise-client-urls https://${CURRENT_IP}:2379 \\
        --listen-peer-urls https://${CURRENT_IP}:2380 \\
        --initial-advertise-peer-urls https://${CURRENT_IP}:2380 \\
        --initial-cluster-token kubernetes-cluster \\
        --initial-cluster \${INITIAL_CLUSTER} \\
        --initial-cluster-state new \\
        --peer-client-cert-auth \\
        --client-cert-auth

Restart=on-failure
RestartSec=5
LimitNOFILE=30000

[Install]
WantedBy=multi-user.target
EOF

curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kubectl -o ${BIN_PATH}/kubectl
chmod +x ${BIN_PATH}/kubectl

mkdir -pv /var/lib/kubernetes/
##
# link certificates from /etc/ssl/kubernetes - these are injected with cloud-init
##

for item in kubernetes-key.pem kubernetes.pem ca.pem ca-key.pem service-accounts.pem; do
    ln -vs /etc/ssl/kubernetes/$item /var/lib/kubernetes/$item
done

cat << EOF > /etc/systemd/system/kube-apiserver-ha.service
[Unit]
Description=Kubernetes API Server
Documentation=https://github.com/kubernetes/kubernetes


[Service]
EnvironmentFile=/etc/systemd/system/etcd.env
ExecStart=/usr/bin/kube-apiserver \\
  --advertise-address=${CURRENT_IP} \\
  --allow-privileged=true \\
  --apiserver-count=3 \\
  --audit-log-maxage=30 \\
  --audit-log-maxbackup=3 \\
  --audit-log-maxsize=100 \\
  --audit-log-path=/var/log/audit.log \\
  --authorization-mode=Node,RBAC \\
  --bind-address=${CURRENT_IP} \\
  --client-ca-file=/var/lib/kubernetes/ca.pem \\
  --cloud-config=/etc/kubernetes/cloud.conf \\
  --cloud-provider=openstack \\
  --enable-admission-plugins=Initializers,NamespaceLifecycle,NodeRestriction,LimitRanger,ServiceAccount,DefaultStorageClass,ResourceQuota \\
  --enable-swagger-ui=true \\
  --enable-bootstrap-token-auth \\
  --etcd-cafile=/var/lib/kubernetes/ca.pem \\
  --etcd-certfile=/var/lib/kubernetes/kubernetes.pem \\
  --etcd-keyfile=/var/lib/kubernetes/kubernetes-key.pem \\
  --etcd-servers=https://\${NODE01_IP}:2379,https://\${NODE02_IP}:2379,https://\${NODE03_IP}:2379 \\
  --event-ttl=1h \\
  --experimental-encryption-provider-config=/var/lib/kubernetes/encryption-config.yaml \\
  --kubelet-certificate-authority=/var/lib/kubernetes/ca.pem \\
  --kubelet-client-certificate=/var/lib/kubernetes/kubernetes.pem \\
  --kubelet-client-key=/var/lib/kubernetes/kubernetes-key.pem \\
  --kubelet-https=true \\
  --runtime-config=api/all \\
  --secure-port 6443 \\
  --service-account-key-file=/var/lib/kubernetes/service-accounts.pem \\
  --service-cluster-ip-range=${CLUSTER_IP_RANGE} \\
  --service-node-port-range=30000-32767 \\
  --tls-cert-file=/var/lib/kubernetes/kubernetes.pem \\
  --tls-private-key-file=/var/lib/kubernetes/kubernetes-key.pem \\
  --token-auth-file=/var/lib/kubernetes/token.csv \\
  --v=2 \\
  --insecure-bind-address=127.0.0.1

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat << EOF > /etc/systemd/system/kube-controller-manager.service
[Unit]
Description=Kubernetes Controller Manager
Documentation=https://github.com/GoogleCloudPlatform/kubernetes

[Service]
ExecStart=/usr/bin/kube-controller-manager \\
  --address=0.0.0.0 \\
  --allocate-node-cidrs=true \\
  --cloud-config=/etc/kubernetes/cloud.conf \\
  --cloud-provider=openstack \\
  --cluster-cidr=${PODS_SUBNET} \\
  --cluster-name=kubernetes \\
  --cluster-signing-cert-file=/var/lib/kubernetes/ca.pem \\
  --cluster-signing-key-file=/var/lib/kubernetes/ca-key.pem \\
  --leader-elect=true \\
  --master=http://127.0.0.1:8080 \\
  --pod-eviction-timeout 30s \\
  --root-ca-file=/var/lib/kubernetes/ca.pem \\
  --service-account-private-key-file=/var/lib/kubernetes/ca-key.pem \\
  --service-cluster-ip-range=${CLUSTER_IP_RANGE} \\
  --node-startup-grace-period 30s \\
  --v=2

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF


cat << EOF > /etc/systemd/system/kube-scheduler.service
[Unit]
Description=Kubernetes Scheduler
Documentation=https://github.com/GoogleCloudPlatform/kubernetes

[Service]
ExecStart=/usr/bin/kube-scheduler \\
  --leader-elect=true \\
  --master=http://127.0.0.1:8080 \\
  --v=2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# setup system init scripts ####################################################

systemctl daemon-reload

systemctl enable etcd
systemctl start etcd

# let etcd start before all k8s components
sleep 5;

for item in etcd kube-apiserver-ha kube-controller-manager kube-scheduler; do
  systemctl enable ${item}
  systemctl start ${item}
done

# install nginx as a proxy
# this is necessary for the load balancer health check
apt-get install -y nginx

cat > kubernetes.default.svc.cluster.local <<EOF
server {
  listen      80;
  server_name kubernetes.default.svc.cluster.local;

  location /healthz {
     proxy_pass                    https://127.0.0.1:6443/healthz;
     proxy_ssl_trusted_certificate /var/lib/kubernetes/ca.pem;
  }
}
EOF

sudo mv kubernetes.default.svc.cluster.local \
    /etc/nginx/sites-available/kubernetes.default.svc.cluster.local

  sudo ln -s /etc/nginx/sites-available/kubernetes.default.svc.cluster.local /etc/nginx/sites-enabled/

sudo systemctl enable nginx
sudo systemctl restart nginx
