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


#setup(
#    author="Oz Tiram",
#    author_email='oz.tiram@noris.de',
#    classifiers=[
#        'Development Status :: 2 - Pre-Alpha',
#        'Intended Audience :: Developers',
#        'Natural Language :: English',
#        'Programming Language :: Python :: 3',
#        'Programming Language :: Python :: 3.5',
#        'Programming Language :: Python :: 3.6',
#    ],
#    description=(
#        "launch kubernetes clusters on OpenStack using ansible-kubespray"),
#    install_requires=requirements,
#    long_description=readme,
#    include_package_data=True,
#    keywords='colt',
#    name='colt',
#    packages=find_packages(include=['colt']),
#    setup_requires=setup_requirements,
#    test_suite='tests',
#    tests_require=test_requirements,
#    url='https://github.com/oz123/colt',
#    version='0.1.0',
#    zip_safe=False,
#)
