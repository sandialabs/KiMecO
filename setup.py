from setuptools import setup, find_packages

VERSION = '0.0.2'
DESCRIPTION = 'KiMecO'
LONG_DESCRIPTION = 'Kinetic Mechanism Optimizer'

# Setting up
setup(
        name="kimeco",
        version=VERSION,
        author="Clement Soulie",
        author_email="<csoulie@sandia.gov>",
        maintainer="Clement Soulie",
        maintainer_email="<csoulie@sandia.gov>",
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        python_requires='>=3.10.14',
        packages=find_packages(),
        install_requires=["ase>=3.22.1",
                          "cantera>=3.0.0",
                          "numpy>=2",
                          "pandas>=2.2",
                          "setuptools>=61.0",
                          "sqlalchemy",
                          "sqlalchemy-utils",
                          "dash",
                          "pint"],

        keywords=['python',
                  'kimeco',
                  'machine learning',
                  'master equation',
                  'kinetics',
                  'kinetic mechanism',
                  'non linear optimizer'],
        classifiers=[
            "Development Status :: 3 - Alpha",
            "Intended Audience :: Research",
            "Programming Language :: Python :: 3",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: Linux",
        ]
)
