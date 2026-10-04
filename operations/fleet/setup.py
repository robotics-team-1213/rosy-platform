from setuptools import find_packages, setup

package_name = 'fleet'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: ['server/web/*.html', 'server/web/*.css', 'server/web/*.js']},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rosy',
    maintainer_email='dev@rosy.local',
    description='ROSY FLEET seed: formation geometry, slot assignment, relay, FOR-004 session',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fleet=fleet.cli:main',
        ],
    },
)
