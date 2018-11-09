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


def is_another_job_running():
    return sum([1 for lin in project.pipelines.list() if lin.attributes['status'] == 'running']) > 1  # noqa


while is_another_job_running() or cinder.volumes.list():
    print("Woha, another job is running, or there are some volumes left "
          "behined ...", flush=True)
    print("In any case I'm waiting ... ", flush=True)
    time.sleep(60)

print("Awesome !!! no jobs and no volume found!")
print("I will run that integration test now!")
