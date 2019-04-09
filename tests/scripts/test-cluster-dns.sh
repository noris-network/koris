
export KUBECONFIG=$1

function fail {
  echo "$1" >&2
  exit 1
}

function retry {
  local n=1
  local max=5
  local delay=15
  while true; do
    "$@" && break || {
      if [[ $n -lt $max ]]; then
        ((n++))
        echo "Command failed. Attempt $n/$max:"
        sleep $delay;
      else
        fail "The command has failed after $n attempts."
      fi
    }
  done
}

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

dig="dig +noall +answer -q"
label="k8s-app=dnscheck"

echo "$dns_checkpod" | kubectl apply -f -

echo -n "Waiting for dnscheck pod to start"

while [ "$(kubectl get pod -l "${label}" -o jsonpath='{.items[0].status.phase}')" != "Running" ]; do
	echo -n "."
	sleep 1
done

function check_dns() {
	hostname=$1
    opts=$2
	desc=$3

	answer="$(kubectl exec dnscheck -- ${dig} "${hostname}" ${opts} -t A 2>&1)"
	if [[ $? -ne 0 || -z "${answer}" ]]; then
		echo -e "\nFailed to resolve ${desc} ${hostname} with check ${dig} $hostname.\nAnswer:" "${answer}"
		#kubectl delete pod -l k8s-app=dnscheck
		exit 1
	else
		echo -e "Successfully resolved $desc:\n${answer}"
    fi
}

retry check_dns "kubernetes.default.svc.cluster.local" "" "FQDN"
retry check_dns "kubernetes.default" "+search" "namespace"
retry check_dns "kubernetes" "+search"  "short name"

# vim: tabstop=4 shiftwidth=4
