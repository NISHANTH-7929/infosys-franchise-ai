"""
Test setup: config.py refuses to load without JWT_SECRET and ADMIN_PASSWORD.
Real secrets (Colab Secrets / .env) win; these throw-away values only fill gaps for the tests.
"""

import os

os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-not-for-real-use-0123456789")
os.environ.setdefault("ADMIN_PASSWORD", "TestOnly@Admin1")
