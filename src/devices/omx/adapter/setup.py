from setuptools import find_packages, setup


package_name = "omx_adapter"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    description="ROS-native OMX adapter profile boundary",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "omx-profile-check=omx_adapter.cli:main",
        ],
    },
)
