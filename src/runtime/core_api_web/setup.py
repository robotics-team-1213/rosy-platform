from setuptools import find_packages, setup

package_name = 'core_api_web'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    # D-129 — 이 패키지가 소유한 대시보드 자산은 복사 설치에서도 빠지지 않아야
    # 한다. symlink 설치는 소스 트리를 직접 가리키므로 이 줄이 없어도 보이지만,
    # 배포 이미지의 복사 설치에서는 이 줄이 없으면 /dashboard·/ui 가 통째로 404다.
    package_data={package_name: [
        'web/*.css', 'web/*.html', 'web/*.js',
    ]},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
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
