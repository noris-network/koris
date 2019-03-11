#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import setup

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('requirements.txt') as r:
    requirements = r.readlines()
    requirements = [r.split(' ', 1) for r in requirements][0]
requirements = []

setup_requirements = ['pytest-runner', ]

test_requirements = ['pytest', ]

setup(
    setup_requires=['pbr'],
    pbr=True,
)


