text/x-shellscript
#!/bin/bash
# bootstrap k8s master without kubeadm / kubespray

#################### project sources and settings ##############################
################################################################################

OS=linux
ARCH=amd64
CLUSTER_IP_RANGE=10.32.0.0/16

# etcd
ETCD_URL=https://github.com/coreos/etcd/releases/download
ETCD_VERSION=v3.3.8

# apiserver, controller-manager, scheduler
K8S_VERSION=v1.10.4
K8S_URL=https://storage.googleapis.com/kubernetes-release/release
BIN_PATH=/usr/bin

###################### Do NOT edit anything below ##############################
################################################################################

source /etc/kolt.conf

CURRENT_IP=$(curl http://169.254.169.254/latest/meta-data/local-ipv4)
HOST_NAME=$(hostname)

# download and setup daemons ###################################################

# etcd
cd /tmp
curl -L ${ETCD_URL}/${ETCD_VERSION}/etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz -O
tar -xvf etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz
cd etcd-${ETCD_VERSION}-${OS}-${ARCH}

for item in "etcd etcdctl"; do
  install -m 775 ${item} ${BIN_PATH}/
done

cat << EOF > /etc/systemd/system/etcd.service
[Unit]
Description=etcd
Documentation=https://github.com/coreos
EnvironmentFile=/etc/kubernetes/etcd_cluster

[Service]
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

# other kubernetes components

for item in "apiserver controller-manager scheduler"; do
    curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kube-${item} -o ${BIN_PATH}/kube-${item}
    chmod +x ${BIN_PATH}/${item}
done

curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kubectl -o ${BIN_PATH}/kubectl
chmod +x ${BIN_PATH}/kubectl


cat << EOF > /etc/systemd/system/kube-apiserver-ha.service
[Service]
[Unit]
Description=Kubernetes API Server
Documentation=https://github.com/GoogleCloudPlatform/kubernetes
EnvironmentFile=/etc/kubernetes/api_cluster

[Service]
ExecStart=/usr/bin/kube-apiserver \
  --admission-control=NamespaceLifecycle,LimitRanger,ServiceAccount,DefaultStorageClass,ResourceQuota \
  --advertise-address=${CURRENT_IP}   \
  --bind-address=0.0.0.0 \
  --audit-log-maxage=30 \
  --audit-log-maxbackup=3 \
  --audit-log-maxsize=100 \
  --audit-log-path=/var/lib/audit.log \
  --allow-privileged=true \
  --authorization-mode=RBAC \
  --enable-swagger-ui=true \
  --etcd-cafile=/var/lib/kubernetes/ca.pem \
  --etcd-certfile=/var/lib/kubernetes/kubernetes.pem \
  --etcd-keyfile=/var/lib/kubernetes/kubernetes-key.pem \
  --kubelet-certificate-authority=/var/lib/kubernetes/ca.pem \
  --client-ca-file=/var/lib/kubernetes/ca.pem \
  --service-cluster-ip-range=${CLUSTER_IP_RANGE} \
  --service-node-port-range=30000-32767 \
  --tls-cert-file=/var/lib/kubernetes/kubernetes.pem \
  --tls-private-key-file=/var/lib/kubernetes/kubernetes-key.pem \
  --enable-bootstrap-token-auth \
  --token-auth-file=/var/lib/kubernetes/token.csv \
  --service-account-key-file=/var/lib/kubernetes/ca-key.pem \
  --runtime-config=batch/v2alpha1=true  \
  --insecure-bind-address=127.0.0.1 \
  --event-ttl=1h \
  --apiserver-count=1 \
  --kubelet-https=true \
  --apiserver-count=3 \
  --runtime-config=api/all \
  --experimental-encryption-provider-config=/var/lib/kubernetes/encryption-config.yaml \
  --etcd-servers=https://{{ node01ip }}:2379,https://{{ node02ip }}:2379,https://{{ node03ip }}:2379 \
  --v=2
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
ExecStart=/usr/bin/kube-controller-manager \
  --cluster-name=kubernetes \
  --leader-elect=true \
  --master=http://127.0.0.1:8080 \
  --root-ca-file=/var/lib/kubernetes/ca.pem \
  --pod-eviction-timeout 30s \
  --service-account-private-key-file=/var/lib/kubernetes/ca-key.pem \
  --cluster-name=kubernetes \
  --cluster-signing-cert-file=/var/lib/kubernetes/ca.pem \
  --cluster-signing-key-file=/var/lib/kubernetes/ca-key.pem \
  --service-cluster-ip-range=${CLUSTER_IP_RANGE} \
  --node-startup-grace-period 30s \
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
ExecStart=/usr/bin/kube-scheduler \
  --leader-elect=true \
  --master=http://127.0.0.1:8080 \
  --v=2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# setup system init scripts ####################################################

# systemctl daemon-reload

#for item in "etcd apiserver controller-manager scheduler"; do
#  systemctl enable ${item}
#  systemctl status ${item}
#done
