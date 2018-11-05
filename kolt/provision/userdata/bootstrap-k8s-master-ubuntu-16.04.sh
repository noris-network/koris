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
K8S_VERSION=v1.11.4
K8S_URL=https://storage.googleapis.com/kubernetes-release/release
BIN_PATH=/usr/bin

###################### Do NOT edit anything below ##############################
################################################################################

CURRENT_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)
HOST_NAME=$(hostname)

# download and setup daemons ###################################################
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
    -f|--fetch) FETCH_ONLY=1; shift;;
    --) shift; break ;;
  esac
done

# check if a binary version is found
# version_check kube-scheduler --version v1.10.4 return 1 if binary is found
# in that version
function version_found() {  return $($1 $2 | grep -qi $3); }

# download a file and set +x on a file
function curlx() { curl -s $1 -o $2 && chmod -v +x $2 ; }

for item in apiserver controller-manager scheduler; do
    version_found kube-${item} --version $K8S_VERSION || curlx ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/kube-${item} ${BIN_PATH}/kube-${item}
done

# etcd
if [ "$(version_found etcd --version ${ETCD_VERSION:1}; echo $?)" -eq 1 ]; then
    echo "etcd version did not match ..."
    cd /tmp
    curl -s -L ${ETCD_URL}/${ETCD_VERSION}/etcd-${ETCD_VERSION}-${OS}-${ARCH}.tar.gz -O
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

if [ ${FETCH_ONLY} -eq 1 ]; then
    echo "finished downloading all binaries"
    exit 0
fi

export DEBCONF_FRONTEND=noninteractive

echo "console-setup   console-setup/charmap47 select  UTF-8" > encoding.conf
debconf-set-selections encoding.conf
rm encoding.conf

apt-get -y update && apt-get -y -o "Dpkg::Options::=--force-confdef" -o "Dpkg::Options::=--force-confold" upgrade && apt-get -y autoclean

cat << EOF > /etc/systemd/system/etcd.service
[Unit]
Description=etcd
Documentation=https://github.com/coreos

[Service]
EnvironmentFile=/etc/systemd/system/etcd.env
ExecStart=/usr/bin/etcd --name=${HOSTNAME} \\
        --data-dir=/var/lib/etcd \\
        --cert-file=/etc/kubernetes/pki/etcd/server.crt \\
        --key-file=/etc/kubernetes/pki/etcd/server.key \\
        --trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt \\
        --client-cert-auth \\
        --peer-cert-file=/etc/kubernetes/pki/etcd/peer.crt \\
        --peer-key-file=/etc/kubernetes/pki/etcd/peer.key  \\
        --peer-trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt \\
        --peer-client-cert-auth \\
        --listen-client-urls https://${CURRENT_IP}:2379,http://127.0.0.1:2379 \\
        --advertise-client-urls https://${CURRENT_IP}:2379 \\
        --listen-peer-urls https://${CURRENT_IP}:2380 \\
        --initial-advertise-peer-urls https://${CURRENT_IP}:2380 \\
        --initial-cluster-token kubernetes-cluster \\
        --initial-cluster \${INITIAL_CLUSTER} \\
        --initial-cluster-state new

Restart=on-failure
RestartSec=5
LimitNOFILE=30000

[Install]
WantedBy=multi-user.target
EOF

mkdir -pv /var/lib/kubernetes/

##
# link certificates from /etc/ssl/kubernetes - these are injected with cloud-init
##

for item in kubernetes-key.pem kubernetes.pem ca.pem ca-key.pem service-accounts.pem service-accounts-key.pem; do
    test -r /etc/ssl/kubernetes/$item && cp -f /etc/ssl/kubernetes/$item /var/lib/kubernetes/$item
done

for item in kubernetes.pem ca.pem; do
    test -r /var/lib/kubernetes/$item && cat /var/lib/kubernetes/$item >> /var/lib/kubernetes/api.cert
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
  --enable-admission-plugins=NamespaceLifecycle,NodeRestriction,LimitRanger,ServiceAccount,DefaultStorageClass,ResourceQuota \\
  --enable-swagger-ui=true \\
  --enable-bootstrap-token-auth \\
  --etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt \\
  --etcd-certfile=/etc/kubernetes/pki/etcd/api-ectd-client.crt \\
  --etcd-keyfile=/etc/kubernetes/pki/etcd/api-ectd-client.key \\
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
  --tls-cert-file=/var/lib/kubernetes/api.cert \\
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
  --service-account-private-key-file=/var/lib/kubernetes/service-accounts-key.pem \\
  --service-cluster-ip-range=${PODS_SUBNET} \\
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

for item in kube-apiserver-ha kube-controller-manager kube-scheduler; do
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
     proxy_pass                    https://${CURRENT_IP}:6443/healthz;
     proxy_ssl_trusted_certificate /var/lib/kubernetes/ca.pem;
  }
}
EOF

mv kubernetes.default.svc.cluster.local \
    /etc/nginx/sites-available/kubernetes.default.svc.cluster.local

ln -s /etc/nginx/sites-available/kubernetes.default.svc.cluster.local /etc/nginx/sites-enabled/

systemctl enable nginx
systemctl restart nginx
