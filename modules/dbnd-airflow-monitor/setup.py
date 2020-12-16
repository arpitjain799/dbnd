from os import path

import setuptools

from setuptools.config import read_configuration


BASE_PATH = path.dirname(__file__)
CFG_PATH = path.join(BASE_PATH, "setup.cfg")

config = read_configuration(CFG_PATH)
version = config["metadata"]["version"]

setuptools.setup(
    name="dbnd-airflow-monitor",
    package_dir={"": "src"},
    install_requires=[
        "dbnd==" + version,
        'simplejson==3.17.0; python_version < "3"',
        "setuptools",
        "prometheus_client",
        "beautifulsoup4==4.9.2",
    ],
    extras_require={
        "tests": [
            "pytest==4.5.0",
            "mock",
            "WTForms<2.3.0",
            "apache-airflow==1.10.9",
            "cattrs==1.0.0",  # airflow requires ~0.9 but it's py2 incompatible (bug)
            "sh",
        ],
        "composer": [
            "PyJWT==1.7.1",
            "cryptography==2.8",
            "google-auth==1.10.0",
            "requests==2.22.0",
            "requests_toolbelt==0.9.1",
            "tzlocal>=1.5.1",
        ],
    },
    entry_points={"dbnd": ["airflow-monitor = airflow_monitor._plugin"]},
)
