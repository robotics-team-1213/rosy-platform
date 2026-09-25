from setuptools import find_packages, setup

package_name = 'core_common'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'pydantic>=2.0'],
    zip_safe=True,
    maintainer='Dev',
    maintainer_email='dev@rosy.com',
    description='Core common',
    license='Proprietary',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
