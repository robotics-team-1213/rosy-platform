from setuptools import find_packages, setup

package_name = "games"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    package_data={"games": ["web/*.html", "web/*.css", "web/*.js"]},
    include_package_data=True,
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/match.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    description="Laptop game host. Not a CORE RobotMode.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "games=games.cli:main",
        ],
    },
)
