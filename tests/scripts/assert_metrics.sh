
# reverse logic applied here to exit with 0 code.
HASMETRICS_NODES=1
HASMETRICS_PODS=1

for i in {1..10}; do
	if kubectl top nodes --kubeconfig=${KUBECONFIG};
		then HASMETRICS_NODES=0; break;
	fi
	sleep 1;
done

for i in {1..10}; do
	if kubectl top pods -n kube-system --kubeconfig=${KUBECONFIG};
		then HASMETRICS_PODS=0; break;
	fi
	sleep 1;
done

# if any of the metrics failed this will be equal 1
exit $(( HASMETRICS_PODS + HASMETRICS_NODES ))
