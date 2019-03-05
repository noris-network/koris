#!/bin/bash

sed -i 's/GSSAPIAuthentication yes/GSSAPIAuthentication no/' /etc/ssh/sshd_config
sed -i 's/UseDNS yes/UseDNS no/' /etc/ssh/sshd_config
systemctl restart sshd
