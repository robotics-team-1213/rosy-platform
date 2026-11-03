from setuptools import find_packages, setup

package_name = 'perception_runtime'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='livsbittt',
    maintainer_email='56295815+livsbittt@users.noreply.github.com',
    description='ROS-free lane perception and learned-model runtime shared by control and learning',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
