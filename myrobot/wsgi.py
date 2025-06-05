"""
WSGI config for myrobot project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myrobot.settings')

try:
    application = get_wsgi_application()
    app = application  # This is needed for Vercel
except Exception as e:
    print(f"Error loading application: {e}")
    raise e