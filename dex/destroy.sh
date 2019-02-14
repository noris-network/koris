#!/bin/bash
kubectl delete -f manifests/dex.yaml
kubectl delete secret dex.example.com.tls
kubectl delete secret gitlab-client