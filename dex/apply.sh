#!/bin/bash
kubectl create secret tls dex.example.com.tls --cert=ssl/cert.pem --key=ssl/key.pem
kubectl create secret \
    generic gitlab-client \
    --from-literal=client-id=1dd9a4fa5381224abca2b9789dcbe5d721367543db44d3b020be48dcbc4156b5 \
    --from-literal=client-secret=674364d762431b2a93e57e4bc2f67eb1d159313b32f848028f28ca23d66c0c76 

kubectl create -f manifests/dex.yaml