
export KUBECONFIG=$1

read -r -d '' dns_checkpod <<EOM
apiVersion: v1
kind: Pod
metadata:
  labels:
    k8s-app: dnscheck
  name: dnscheck
  namespace: default
spec:
  containers:
    - name: dnscheck
      image: tutum/dnsutils
      command:
      - "sleep"
      args:
      - "86400"
EOM

dns_check_hostname="kubernetes"
dns_check_namespace="default"
dns_check_cluster_domain="svc.cluster.local"
dns_check_with_search_domains="${dns_check_hostname}.${dns_check_namespace}"
dns_check_fqdn="${dns_check_with_search_domains}.${dns_check_cluster_domain}"
dig="dig +noall +answer -q"
label="k8s-app=dnscheck"

echo "$dns_checkpod" | kubectl apply -f -

echo -n "Waiting for dnscheck pod to start"

while [ $(kubectl get pod -l "${label}" -o jsonpath='{.items[0].status.phase}') != "Running" ]; do
	echo -n "."
	sleep 1
done

function check_dns() {
	hostname=$1
	desc=$2
	long_desc=$3

	echo -e $long_desc

	answer=$(kubectl exec dnscheck -- $dig ${hostname} -t A 2>&1)
	if [[ $? -ne 0 ]]; then
		echo -e "\nFailed to resolve ${desc} ${hostname} with check "${dig} $hostname".\nAnswer: ${answer}"
		kubectl delete pod -l k8s-app=dnscheck
		exit 1
	else
		echo -e "Successfully resolved $desc:\n${answer}"
fi
}

check_dns $dns_check_fqdn "FQDN" '\nFirst checking FQDN resolving'
check_dns $dns_check_with_search_domains 'short name' '\nNow checking short name, using search domains'

# vim: tabstop=4 shiftwidth=4
