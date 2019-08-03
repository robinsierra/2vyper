#!/usr/bin/env python3

from setuptools import setup, find_packages


setup(
        name='2vyper',
        version='0.0.1',
        author='Viper Team',
        author_email='viper@inf.ethz.ch',
        license='MPL-2.0',
        packages=find_packages('src'),
        package_dir={'': 'src'},
        package_data={
            'nagini_translation.resources': ['*.vpr'],
            'nagini_translation.backends': ['*.jar']
        },
        requires=[
            'distribute',
            ],
        install_requires=[
            'jpype1==0.6.3',
            'astunparse==1.6.2',
            'z3-solver',
            'vyper'
            ],
        entry_points={
             'console_scripts': [
                 '2vyper = nagini_translation.main:main',
                 ]
             },
        url='http://www.pm.inf.ethz.ch/research/nagini.html',
        description='Static verifier for Vyper, based on Viper.',
        long_description=(open('README.rst').read()),
        # Full list of classifiers could be found at:
        # http://pypi.python.org/pypi?%3Aaction=list_classifiers
        classifiers=[
            'Development Status :: 3 - Alpha',
            'Environment :: Console',
            'Intended Audience :: Developers',
            'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
            'Operating System :: OS Independent',
            'Programming Language :: Python :: 3 :: Only',
            'Topic :: Software Development',
            ],
        )
