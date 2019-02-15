#!/bin/bash
kubectl delete -f manifests/
kubectl delete secret dex.example.com.tls
kubectl delete secret gitlab-client
kubectl delete secret dex.example.com.root-ca