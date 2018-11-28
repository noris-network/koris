Prometheus Operator:
====================

Install and configure prometheus in a dedicated namespace.

Intalling:

First edit the file `addons/prometheus/42_prometheus_Prometheus.yaml` and set the variables:

```
    cluster: ${CLUSTER_NAME}
    customer: ${CUSTOMER_NAME}
```

Then apply the operator:

```
kubctl apply -f addons/prometheus
```

To verify that the operator works:

```
$ kubectl get pods -n nn-mon
NAME                                   READY     STATUS    RESTARTS   AGE
kube-state-metrics-6dfc9b9844-dbcwb    4/4       Running   2          1m
node-exporter-7v66g                    2/2       Running   0          1m
node-exporter-8bl55                    2/2       Running   0          1m
node-exporter-gcclm                    2/2       Running   0          1m
node-exporter-gtx82                    2/2       Running   0          1m
node-exporter-rbzsx                    2/2       Running   0          1m
node-exporter-sfzc9                    2/2       Running   0          1m
node-exporter-sqj59                    2/2       Running   0          1m
node-exporter-wwg84                    2/2       Running   0          1m
node-exporter-xhjc4                    2/2       Running   0          1m
prometheus-operator-6bc559bf68-rppvs   1/1       Running   2          1m
```

The is also a NodePort where Prometheus is listening on.

To see it issue:

```
$ kubectl get svc -n nn-mon
NAME                  TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)             AGE
kube-state-metrics    ClusterIP   None           <none>        8443/TCP,9443/TCP   7m
nn-prometheus         NodePort    10.107.65.43   <none>        9090:31744/TCP      7m
node-exporter         ClusterIP   None           <none>        9100/TCP            7m
prometheus-operator   ClusterIP   None           <none>        8080/TCP            7m
```

To add this prometheus to the IAAS prometheus, you need to configure the cluster
loadbalancer to redirect to the Prometheus service port (in the above example 31744).


In case you see the following series of errors:
```
rolebinding.rbac.authorization.k8s.io/prometheus-k8s created
service/nn-prometheus created
unable to recognize "prometheus/02_operator_serviceMonitor.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/22_kube_serviceMonitor.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/32_node_serviceMonitor.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_Prometheus.yaml": no matches for kind "Prometheus" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_PrometheusRule.yaml": no matches for kind "PrometheusRule" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_ServiceMonitor.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_ServiceMonitorApiserver.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_ServiceMonitorCoreDNS.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_ServiceMonitorKubeControllerManager.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_ServiceMonitorKubeScheduler.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
unable to recognize "prometheus/42_prometheus_ServiceMonitorKubelet.yaml": no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
```

reapply ...
