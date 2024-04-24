from setuptools import setup, find_packages

VERSION = '0.0.1' 
DESCRIPTION = 'GAME'
LONG_DESCRIPTION = 'Genetic Algorythm Master Equation'

# Setting up
setup(
       # the name must match the folder name 'verysimplemodule'
        name="game", 
        version=VERSION,
        author="Clement Soulie",
        author_email="<csoulie@sandia.gov>",
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        python_requires='>=3.10.14',
        packages=find_packages(),
        install_requires=['ase>=3.22.1'], # add any additional packages that 
        # needs to be installed along with your package. Eg: 'caer'
        
        keywords=['python',
                  'game',
                  'genetic algorythm',
                  'master equation',
                  'kinetics'],
        classifiers= [
            "Development Status :: 3 - Alpha",
            "Intended Audience :: Research",
            "Programming Language :: Python :: 3",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: Linux",
        ]
)