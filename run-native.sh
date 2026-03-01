#!/bin/bash
# RIB Analyze Native Launcher
# Starts the RIB Analyze TUI application

# Check if virtual environment is active
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Virtual environment not activated!"
    echo "Please run:"
    echo "  source .venv/bin/activate"
    echo "Then:"
    echo "  ./run-native.sh"
    exit 1
fi

# Check if dependencies are installed
python -c "import textual; print('Dependencies OK')" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Missing dependencies!"
    echo "Please run: source .venv/bin/activate && pip install -r tui/requirements.txt"
    exit 1
fi

# Display welcome message
echo ""
echo "╔════════════════════════════════════════╗"
echo "║        RIB ANALYZE - NATIVE MODE       ║"
echo "║        Routing Table Analysis          ║"
echo "║                                        ║"
echo "║   [c] Connect   [d] Disconnect         ║"
echo "║   [i] Import    [e] Export             ║"
echo "║   [r] Refresh   [h] Help   [q] Quit    ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Run the application
python run.py