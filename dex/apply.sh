#!/bin/bash
kubectl create secret tls dex.example.com.tls --cert=ssl/cert.pem --key=ssl/key.pem
kubectl create secret \
    generic gitlab-client \
    --from-literal=client-id=9594acc6725a0a988c760cbdef5171c581e390e61752641380d2aa682d578fa6 \
    --from-literal=client-secret=7671ac33872513fc65e9d975c9a55cd53e60ab98ff0b30ec42bba6fdae8a56b9 

kubectl create -f manifests/dex.yaml