import os
import sys

# Add root folder to sys.path so agent_reach and web_app are importable
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from web_app import app
