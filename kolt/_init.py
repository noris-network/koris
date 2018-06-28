"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import os
import textwrap

from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


INCLUSION_TYPES_MAP = {
    '#include': 'text/x-include-url',
    '#include-once': 'text/x-include-once-url',
    '#!': 'text/x-shellscript',
    '#cloud-config': 'text/cloud-config',
    '#upstart-job': 'text/upstart-job',
    '#part-handler': 'text/part-handler',
    '#cloud-boothook': 'text/cloud-boothook',
    '#cloud-config-archive': 'text/cloud-config-archive',
    '#cloud-config-jsonp': 'text/cloud-config-jsonp',
}


class CloudInit:

    def __init__(self, role, cluster_info, os_type='ubuntu', os_version="16.04"):
        self.combined_message = MIMEMultipart()

        if role not in ('master', 'node'):
            raise ValueError("Incorrect os_role!")

        self.role = role
        self.cluster_info = cluster_info
        self.os_type = os_type
        self.os_version = os_version

    def _etcd_cluster_info(self):
        """
        Write the etcd cluster info to /etc/kolt.conf
        """
        
        cluster_info_part = """
        #cloud-config
        write_files:
            - content: |
                NODE01={n01_name}
                NODE02={n02_name}
                NODE03={n03_name}
                NODE01_IP={n01_ip}
                NODE02_IP={n02_ip}
                NODE03_IP={n03_ip}
              
              owner: root:root
              permissions: '0644'
              path: /etc/kolt.conf
        """.format(**self.cluster_info)
        return textwrap.dedent(cluster_info_part)

    def __str__(self):

        if self.cluster_info:
           sub_message = MIMEText(self._etcd_cluster_info(), _subtype='text/cloud-config')
           sub_message.add_header('Content-Disposition', 'attachment',
                                  filename="/etc/kolt.conf")

           self.combined_message.attach(sub_message)
         
        k8s_bootstrap = "bootstrap-k8s-%s-%s-%s.sh" % (self.role,
                                                       self.os_type,
                                                       self.os_version)

        for item in ['generic', k8s_bootstrap]:
            fh = open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt',
                                                     'cloud-inits',
                                                     item)))
            # we currently blindly assume the first line is a mimetype
            # or a shebang
            main_type, _subtype = fh.readline().strip().split("/", 1)

            if '#!' in main_type:
                _subtype = 'x-shellscript'
                fh.seek(0)

            sub_message = MIMEText(fh.read(), _subtype=_subtype)
            sub_message.add_header('Content-Disposition',
                                   'attachment', filename="%s" % item)
            self.combined_message.attach(sub_message)
            fh.close()
	
        return self.combined_message.as_string()
