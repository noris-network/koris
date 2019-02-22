#!/bin/bash
kubectl create secret tls dex.example.com.tls \
    --cert=/home/aknipping/work/koris/certs-ajk-dex/dex-client.pem \
    --key=/home/aknipping/work/koris/certs-ajk-dex/dex-client-key.pem

kubectl create secret generic gitlab-client \
    --from-literal=client-id=a920735e852804d31c4eec23b6fe548a79509a5722c72c363eeeeb1283851140 \
    --from-literal=client-secret=7c06d2c9ebd25eb20595b0e5fc82f2b3a4c9f5b673cbc43da375c6f4af5a5746
    
kubectl create secret generic dex.example.com.root-ca \
    --from-file=/home/aknipping/work/koris/certs-ajk-dex/dex-ca.pem

kubectl create -f manifests/