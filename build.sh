#!/bin/bash

# Install dependencies
pip install -r requirements.txt

# Create temporary directory for static files
mkdir -p /tmp/static

# Set environment variable for static root
export STATIC_ROOT=/tmp/static

# Collect static files
python manage.py collectstatic --noinput

# Create static directory in the project
mkdir -p static

# Copy collected static files to the project's static directory
cp -r /tmp/static/* static/ 