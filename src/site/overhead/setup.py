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
    install_requires=["setuptools"],
    zip_safe=True,
    description="Receive-only rosy-overhead/1 ingest adapter.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "rosy_overhead=overhead.cli:main",
        ],
    },
)
