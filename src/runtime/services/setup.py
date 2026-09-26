from setuptools import find_packages, setup

package_name = 'core_features'

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
    maintainer='Dev',
    maintainer_email='dev@rosy.com',
    description='Core Features',
    license='Proprietary',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
