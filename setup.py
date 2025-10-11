from setuptools import setup, find_packages


setup(
    name="llm-proxy-api",
    version="0.1.0",
    author="RadLab team",
    packages=find_packages(exclude=("tests", "docs")),
    python_requires=">=3.10",
    entry_points={},
    install_requires=open("requirements.txt").read().splitlines(),
)
