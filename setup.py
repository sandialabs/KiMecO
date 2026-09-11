from setuptools import setup, find_packages

VERSION = '1.1.7'
DESCRIPTION = 'KiMecO'
LONG_DESCRIPTION = 'Kinetic Mechanism Optimizer'

# Setting up
setup(
        name="kimeco",
        version=VERSION,
        author="Clement Soulie",
        author_email="clement.soulie31@gmail.com",
        maintainer="Clement Soulie",
        maintainer_email="clement.soulie31@gmail.com",
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        python_requires='>=3.11',
        packages=find_packages(),
        install_requires=["ase>=3.22.1",
                          "cantera>=3.0.0",
                          "numpy>=2",
                          "pandas>=2.2",
                          "sqlalchemy",
                          "sqlalchemy-utils",
                          "dash",
                          "scipy>=1.10",
                          "plotly>=5",
                          "pint",
                          "pyarrow>=14"],
        extras_require={"test": ["pytest>=9.0.2"],
                        "automech": ["autoio>=0.2026.0",
                                     "autochem>=0.2025.0,<2.0.0",
                                     "mako>=1.3.10",
                                     "more-itertools>=10.8.0",
                                     "networkx>=3.3",
                                     "pint>=0.25",
                                     "pyparsing>=3.2.5",
                                     "pyyaml>=6.0.3",
                                     "qcelemental>=0.29.0",
                                     "rdkit>=2025.9.1",
                                     "scipy>=1.12",
                                     "xarray>=2023.8"]},

        keywords=['python',
                  'kimeco',
                  'machine learning',
                  'master equation',
                  'kinetics',
                  'kinetic mechanism',
                  'non linear optimizer'],
        classifiers=[
            "Development Status :: 3 - Alpha",
            "Intended Audience :: Science/Research/Kinetics",
            "Programming Language :: Python :: 3",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: Linux",
        ]
)
