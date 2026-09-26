from setuptools import find_packages, setup

package_name = "overhead"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=[
        "setuptools",
        "websockets>=14",
        "httpx>=0.27,<1",
        "numpy>=1.26,<3",
        "opencv-contrib-python-headless>=4.9,<5",
    ],
    zip_safe=True,
    description="ROS-free overhead camera ingest and display-only vision worker.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "rosy_overhead=overhead.cli:main",
        ],
    },
)
