#!/bin/bash

# This script is for twiking Cento 7 Noris Cloud  images

systemctl disable firewalld
systemctl stop firewalld
swapoff -a

sed -i 's/'$(hostname -s)'.noriscloud //g' /etc/hosts
sed -i 's/^search/#search/g' /etc/resolv.conf

hostnamectl set-hostname $(hostname -s)
