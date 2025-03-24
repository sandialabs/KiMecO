from setuptools import setup, find_packages

VERSION = '0.0.1'
DESCRIPTION = 'GAME'
LONG_DESCRIPTION = 'Genetic Algorythm Master Equation'

# Setting up
setup(
        name="game",
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
                          "numpy>=1.22.4",
                          "pandas>=2.2",
                          "setuptools>=61.0",
                          "sqlalchemy"],  # add any additional packages that

        keywords=['python',
                  'game',
                  'machine learning',
                  'master equation',
                  'kinetics'],
        classifiers=[
            "Development Status :: 3 - Alpha",
            "Intended Audience :: Research",
            "Programming Language :: Python :: 3",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: Linux",
        ]
)
