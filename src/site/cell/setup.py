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
    install_requires=["setuptools", "rosy-palletizing==0.1.0"],
    zip_safe=True,
    description="Legacy ROS package and import facade for the ROS-free palletizing process wheel.",
    license="Apache-2.0",
)
