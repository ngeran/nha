#!/usr/bin/env python3
"""
RIB Monitor - Setup script for native development
Creates virtual environment and installs dependencies.
"""

import subprocess
import sys
import os


def run_command(cmd, check=True, capture_output=False):
    """Run a shell command."""
    print(f"Running: {cmd}")
    result = subprocess.run(
        cmd, shell=True, check=check, capture_output=capture_output, text=True
    )
    if capture_output:
        return result.stdout.strip()
    return result


def main():
    """Main setup function."""
    print("Setting up RIB Monitor for native development...")

    # Create virtual environment
    venv_path = ".venv"
    if not os.path.exists(venv_path):
        print(f"Creating virtual environment at {venv_path}")
        run_command(f"python3 -m venv {venv_path}")

    # Activate virtual environment
    if os.name == "nt":  # Windows
        activate_cmd = f"{venv_path}\\Scripts\\activate"
    else:  # Unix/Mac
        activate_cmd = f"source {venv_path}/bin/activate"

    print(f"\nTo activate the virtual environment, run:")
    print(f"  {activate_cmd}")

    # Install dependencies
    print("\nInstalling dependencies...")
    run_command(f"{venv_path}/bin/pip install --upgrade pip")
    run_command(f"{venv_path}/bin/pip install -r backend/requirements.txt")
    run_command(f"{venv_path}/bin/pip install -r tui/requirements.txt")

    # Create data directories
    print("\nCreating data directories...")
    os.makedirs("rib-data", exist_ok=True)

    # Create empty baseline files
    baseline_files = [
        "rib-data/baseline-routes.xml",
        "rib-data/baseline-routes.json",
        "rib-data/baseline-routes.yaml",
    ]

    for file_path in baseline_files:
        if not os.path.exists(file_path):
            print(f"Creating {file_path}")
            with open(file_path, "w") as f:
                if file_path.endswith(".xml"):
                    f.write("<routes></routes>\n")
                elif file_path.endswith(".json"):
                    f.write("[]\n")
                elif file_path.endswith(".yaml"):
                    f.write("routes: []\n")

    print("\nSetup complete!")
    print("\nTo run the application:")
    print(f"  {activate_cmd}")
    print("  python tui/app/main.py")

    print("\nTo run tests:")
    print(f"  {activate_cmd}")
    print("  python tests/test_engine.py")


if __name__ == "__main__":
    main()
