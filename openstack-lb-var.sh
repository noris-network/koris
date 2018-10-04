#!/bin/bash

export LB_CONFIG='{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer": "true"}}}}}'
