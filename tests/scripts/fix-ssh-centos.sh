#!/bin/bash

# This script is for fixing slow ssh on CentOS 7 generic images

sed -i 's/GSSAPIAuthentication yes/GSSAPIAuthentication no/' /etc/ssh/sshd_config
sed -i 's/UseDNS yes/UseDNS no/' /etc/ssh/sshd_config
sed -i 's/#UseDNS no/UseDNS no/' /etc/ssh/sshd_config


systemctl disable firewalld
systemctl stop firewalld
swapoff -a

sed -i 's/'$(hostname -s)'.noriscloud //g' /etc/hosts
sed -i 's/^search/#search/g' /etc/resolv.conf

hostnamectl set-hostname $(hostname -s)

systemctl restart sshd
