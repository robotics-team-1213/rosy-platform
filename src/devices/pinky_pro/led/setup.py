from setuptools import find_packages, setup

package_name = 'led'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pl3',
    maintainer_email='kyung133851@pinklab.art',
    description='ROSY LED expression server',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'led_server=led.led_server:main'
        ],
    },
)
