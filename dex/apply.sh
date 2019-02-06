#!/bin/bash
kubectl create secret tls dex.example.com.tls --cert=ssl/cert.pem --key=ssl/key.pem
kubectl create -f manifests/dex.yaml