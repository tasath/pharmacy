import sys
import os

# Add backend folder to path so app_clean can be imported
backend_path = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(backend_path))
