from glob import glob
import os

from setuptools import find_packages, setup


PACKAGE_NAME = "fleet_navigation"


setup(
    name=PACKAGE_NAME,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + PACKAGE_NAME],
        ),
        ("share/" + PACKAGE_NAME, ["package.xml"]),
        (
            os.path.join("share", PACKAGE_NAME, "launch"),
            glob("launch/*.launch.py"),
        ),
        (
            os.path.join("share", PACKAGE_NAME, "config"),
            glob("config/*.yaml"),
        ),
        (
            os.path.join("share", PACKAGE_NAME, "maps"),
            glob("maps/*"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="spongebobDG",
    maintainer_email="eorjs135795@gmail.com",
    description="Safe SLAM and Nav2 bringup for TurtleBot fleet robots.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "validate_map = fleet_navigation.map_validator:main",
            "scan_normalizer = fleet_navigation.scan_normalizer:main",
            "supervised_motion = fleet_navigation.supervised_motion:main",
        ],
    },
)
