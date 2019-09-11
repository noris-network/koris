========
Security
========

This document describe the security features of Koris.

Audit Logging
-------------

Per default Kubernetes does not log access to the Kubernetes API. In koris every
request to the API server is logged as a security measure. Each acceess using
``kubectl`` or an HTTPS using curl (or similar), contains information of who
asked what, when and from where, and the Kubernetes API server can log this
information and the response sent. For more information see the
`official audit logging documentation`_.

Currently, koris clusters use the same audit policy used by Google's Kubernetes
servers. You can look at the link to examine the `policy for koris`_.

All audit logs are saved in the masters' filesystem in a form of files.
You can find the log files under `/var/log/kubrenetes/audit.log`. Note that in
HA clusters the logs are fragmented. That means that subsequent requests
will have logs found in multiple files scattered among your cluster masters.
Future versions of koris will add a central logging mechanism.

On each of the masters there are multiple log files under `/var/log/kubernetes/`.
The latest log file is `/var/log/kubernetes/audit.log` multiple other files
will be save with the following name schema: `/var/log/kubernetes/audit-YYYY-MM-DDTHH-MM-SS.XXX.log`
This represents the date the current file reach a maximum age or maximum size.
On each master a maximum of 30 files. The max age of the current file is 30 days
and the current maximum size of each log file is 24MB. These options are controlled
by command line flags passed to `kube-apiserver` and are currently not configurable
by the user of koris.

.. _official audit logging documentation: https://kubernetes.io/docs/tasks/debug-application-cluster/audit/#audit-policy

.. _policy for koris: https://github.com/kubernetes/kubernetes/blob/master/cluster/gce/gci/configure-helper.sh#L832
