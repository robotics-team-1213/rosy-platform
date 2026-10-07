from setuptools import find_packages, setup

package_name = "rosy_vision"

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
            "rosy-vision=rosy_vision.cli:main",
            "rosy-lane-map=rosy_vision.lane_map:main",
            # D-377 3: old names kept for one site candidate release; both removed in stage 5.
            "site_vision=rosy_vision.cli:main",
            "overhead=rosy_vision.cli:main",
        ],
    },
)
