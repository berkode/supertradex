#!/bin/bash

# Navigate to your project directory
cd /Users/morpheus/berkode/synthron

# # Create a new virtual environment
# python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Install the required packages with the --use-pep517 option
pip3 install --use-pep517 -r requirements.txt

# Verify the installation of the requests module
python3 -c "import requests; print(requests.__version__)"

# Run the script
python3 /Users/morpheus/berkode/synthron/main.py