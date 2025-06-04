#!/bin/bash

# Exit on error
set -e

echo "Installing dependencies..."
python3.9 -m pip install --upgrade pip
python3.9 -m pip install -r requirements.txt

echo "Creating static directory..."
mkdir -p static

echo "Collecting static files..."
python3.9 manage.py collectstatic --noinput --clear

echo "Build completed." 