#!/bin/python3
import os
import time

from urllib.parse import urlparse
import gitlab


from kolt.cloud.openstack import get_clients

_, _, cinder = get_clients()

URL = urlparse(os.getenv("CI_PROJECT_URL"))
gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                   private_token=os.getenv("ACCESS_TOKEN"))


project = gl.projects.get(os.getenv("CI_PROJECT_ID"))


def is_job_running():
    return 'running' in [lin.attributes['status'] for
                         lin in project.pipelines.list()]


while is_job_running() or cinder.volumes.list():
    print("Woha, another job is running, or there are some volumes left behined ...")
    print("In any case I'm waiting ... ")
    time.sleep(60)
