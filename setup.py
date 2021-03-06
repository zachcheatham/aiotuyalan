import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

with open("requirements.txt", "r") as fh:
    requires = fh.read().splitlines()

setuptools.setup(
    name="aiotuyalan",
    version="0.0.3",
    author="Zach Cheatham",
    author_email="zachcheatham@gmail.com",
    description="Python library for interacting with Tuya-based devices using asyncio",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/zachcheatham/async-tuya",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=requires,
    python_requires='>=3.5.3'
)
