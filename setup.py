from setuptools import setup, find_packages

def read_requirements():
    """Read requirements from requirements.txt file."""
    with open('requirements.txt', 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="supertradex",
    version="2.0",
    packages=find_packages(),
    install_requires=read_requirements(),
    python_requires=">=3.11",
    entry_points={
        'console_scripts': [
            'supertradex=supertradex.main:main',
        ],
    },
    # Modern packaging configuration
    setup_requires=['setuptools>=64.0.0'],
) 