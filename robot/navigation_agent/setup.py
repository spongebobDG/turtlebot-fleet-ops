from glob import glob
import os

from setuptools import find_packages, setup


package_name = "navigation_agent"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            [f"resource/{package_name}"],
        ),
        (f"share/{package_name}", ["package.xml"]),
        (
            os.path.join("share", package_name, "config"),
            glob("config/*.yaml"),
        ),
        (
            os.path.join("share", package_name, "launch"),
            glob("launch/*.launch.py"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="spongebobDG",
    maintainer_email="eorjs135795@gmail.com",
    description=(
        "Robot-local Nav2 goal ownership, fleet leases, and motion-source "
        "arbitration."
    ),
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "navigation_agent_node = navigation_agent.agent_node:main",
            "motion_arbiter_node = navigation_agent.arbiter_node:main",
            "validate_map = navigation_agent.map_validator:main",
            "scan_normalizer = navigation_agent.scan_normalizer:main",
            "supervised_motion = navigation_agent.supervised_motion:main",
        ],
    },
)
