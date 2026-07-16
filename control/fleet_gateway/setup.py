from glob import glob
import os

from setuptools import find_packages, setup


package_name = "fleet_gateway"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        ("share/" + package_name, ["package.xml"]),
        (
            os.path.join("share", package_name, "launch"),
            glob("launch/*.launch.py"),
        ),
        (
            os.path.join("share", package_name, "config"),
            glob("config/*.yaml"),
        ),
        (
            os.path.join("share", package_name, "web"),
            glob("web/*"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="spongebobDG",
    maintainer_email="eorjs135795@gmail.com",
    description="Bridge ROS 2 fleet status and commands to a web API.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "fleet_gateway = fleet_gateway.main:main",
        ],
    },
)
