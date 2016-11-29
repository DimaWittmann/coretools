# This file is adapted from python code released by WellDone International
# under the terms of the LGPLv3.  WellDone International's contact information is
# info@welldone.org
# http://welldone.org
#
# Modifications to this file from the original created at WellDone International 
# are copyright Arch Systems Inc.

#Caveats and possible issues
#Mac OS X
# - when using a virtualenv, readline is not properly installed into the virtualenv
#   and cannot be imported.  You need to install it using easy_install as described here
#   http://calvinx.com/tag/readline/
#
# NB There is a required manual post-install step to register iotilebuild with the iotile command
# so that you can use the iotile build command.  Run
# > iotile registry add_plugin build iotilebuild.build.build,build

from setuptools import setup, find_packages

import os

version = "2.0.0"

def list_data_files():
    result = []
    dirname = os.path.join(os.path.dirname(__file__), 'iotile', 'build')
    for root, _, files in os.walk(os.path.join(dirname, 'config')):
        for filename in files:
            result.append(os.path.join(root, filename)[len(dirname)+1:])
    return result



setup(
    name="iotilebuild",
    packages=find_packages(exclude=("test",)),
    version=version,
    license="LGPLv3",
    install_requires=[
        "iotilecore>=3.0.0",
        "sphinx>=1.3.1",
        "scons==2.5.0",
        "breathe==4.2.0",
        "pygtrie>=2.0.0"
    ],
    package_data={
        'iotilebuild': list_data_files()
    },
    entry_points={'iotile.plugin': ['.build = iotile.build.plugin:setup_plugin']},
    description="IOTile Build Support",
    author="Arch",
    author_email="info@arch-iot.com",
    url="http://github.com/iotile/lib_iotilecore",
    keywords=["iotile", "arch", "embedded", "hardware", "firmware"],
    classifiers=[
        "Programming Language :: Python",
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules"
        ],
    long_description="""\
IOTileBuild
------

A python package for build embedded firmware on IOTile based devices.  See https://www.arch-iot.com.

"""
)