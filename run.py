#!/usr/bin/env python3
"""
RIB Analyze - Launcher script for running the application
"""

import sys
import os


def main():
    """Launch RIB Analyze TUI."""
    # Check if virtual environment is active
    if "VIRTUAL_ENV" not in os.environ:
        print("Virtual environment not activated!")
        print("Please run:")
        print("  source .venv/bin/activate")
        print("Then:")
        print("  python run.py")
        sys.exit(1)

    # Add project root to Python path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Import and run the app
    try:
        from tui.app.main import RIBAnalyze

        print("Starting RIB Analyze...")
        app = RIBAnalyze()
        app.run()
    except ImportError as e:
        print(f"Failed to import application: {e}")
        print("Make sure all dependencies are installed:")
        print("  pip install -r backend/requirements.txt")
        print("  pip install -r tui/requirements.txt")
        sys.exit(1)


if __name__ == "__main__":
    main()
