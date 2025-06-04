#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Creating static directory..."
mkdir -p static

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Build completed." 