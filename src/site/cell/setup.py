from setuptools import find_packages, setup

package_name = "rosy_cell"

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
    description="ROS-free palletizing recipes, taught cell frames and Job compilation.",
    license="Apache-2.0",
)
