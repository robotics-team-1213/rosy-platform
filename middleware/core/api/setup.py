from setuptools import find_packages, setup

package_name = 'core_api_web'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'core_common>=0.0.2', 'cryptography==50.0.0'],
    zip_safe=True,
    maintainer='Dev',
    maintainer_email='dev@rosy.com',
    description='Core API and Web',
    license='Proprietary',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
