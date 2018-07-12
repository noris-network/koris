text/x-shellscript
#!/bin/bash
# bootstrap k8s master without kubeadm / kubespray

#################### project sources and settings ##############################
################################################################################

OS=linux
ARCH=amd64
CLUSTER_IP_RANGE=10.32.0.0/16
PODS_SUBNET=10.233.64.0/18
# etcd
ETCD_URL=https://github.com/coreos/etcd/releases/download
ETCD_VERSION=v3.2.23

# apiserver, controller-manager, scheduler
K8S_VERSION=v1.10.4
K8S_URL=https://storage.googleapis.com/kubernetes-release/release
BIN_PATH=/usr/bin

###################### Do NOT edit anything below ##############################
################################################################################

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

# other kubernetes components

for item in apiserver controller-manager scheduler; do
    curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kube-${item} -o ${BIN_PATH}/kube-${item}
    chmod -v +x ${BIN_PATH}/kube-${item}
done

curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kubectl -o ${BIN_PATH}/kubectl
chmod +x ${BIN_PATH}/kubectl

mkdir -pv /var/lib/kubernetes/
##
# link certificates from /etc/ssl/kubernetes - these are injected with cloud-init
##
ln -vs /etc/ssl/kubernetes/kubernetes-key.pem /var/lib/kubernetes/kubernetes-key.pem
ln -vs /etc/ssl/kubernetes/kubernetes.pem /var/lib/kubernetes/kubernetes.pem
ln -vs /etc/ssl/kubernetes/ca.pem /var/lib/kubernetes/ca.pem
ln -vs /etc/ssl/kubernetes/service-accounts.pem /var/lib/kubernetes/service-accounts.pem
###
# create authentication tokens for calico, admin and kubelet service
###

adminToken=$(tr -cd '[:alnum:]' < /dev/urandom | fold -w30 | head -n 1)
calicoToken=$(tr -cd '[:alnum:]' < /dev/urandom | fold -w30 | head -n 1)
kubeletToken=$(tr -cd '[:alnum:]' < /dev/urandom | fold -w30 | head -n 1)

cat > /var/lib/kubernetes/token.csv << EOF
${adminToken},admin,admin,"cluster-admin,system:masters"
${calicoToken},calico,calico,"cluster-admin,system:masters"
${kubeletToken},kubelet,kubelet,"cluster-admin,system:masters"
EOF

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
  --bind-address=0.0.0.0 \\
  --client-ca-file=/var/lib/kubernetes/ca.pem \\
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
  --service-account-key-file=/var/lib/kubernetes/service-accounts.pem \\
  --service-cluster-ip-range=${CLUSTER_IP_RANGE} \\
  --service-node-port-range=30000-32767 \\
  --tls-cert-file=/var/lib/kubernetes/kubernetes.pem \\
  --tls-private-key-file=/var/lib/kubernetes/kubernetes-key.pem \\
  --token-auth-file=/var/lib/kubernetes/token.csv \\
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
ExecStart=/usr/bin/kube-controller-manager \\
  --address=0.0.0.0 \\
  --cluster-cidr=${PODS_SUBNET} \\
  --cluster-name=kubernetes \\
  --cluster-signing-cert-file=/var/lib/kubernetes/ca.pem \\
  --cluster-signing-key-file=/var/lib/kubernetes/ca-key.pem \\
  --leader-elect=true \\
  --master=http://${CURRENT_IP}:8080 \\
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
  --master=http://${CURRENT_IP}:8080 \\
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
