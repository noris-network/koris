#!/bin/bash

OS_LB=$(echo "'{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer:": "true"}}}}}'")
