#!/bin/bash

export OS_LB='{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer:": "true"}}}}}'
