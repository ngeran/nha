#!/bin/bash
# Watch log files in real-time

LOG_DIR="$(dirname "$0")/logs"

echo "RIB Monitor Log Viewer"
echo "======================"
echo ""
echo "Log files:"
echo "  1. rib_monitor.log - Main log"
echo "  2. error.log       - Errors only"
echo "  3. debug.log       - Debug (most detailed)"
echo ""

# Check if logs exist
if [ ! -d "$LOG_DIR" ]; then
    echo "Logs directory not found: $LOG_DIR"
    echo "Logs will be created when the app runs."
    exit 1
fi

# Default to debug log
LOG_FILE="${1:-$LOG_DIR/debug.log}"

if [ ! -f "$LOG_FILE" ]; then
    # If specific file doesn't exist, try as just a number or name
    case "$1" in
        1|main) LOG_FILE="$LOG_DIR/rib_monitor.log" ;;
        2|error) LOG_FILE="$LOG_DIR/error.log" ;;
        3|debug) LOG_FILE="$LOG_DIR/debug.log" ;;
        *) LOG_FILE="$LOG_DIR/debug.log" ;;
    esac
fi

echo "Watching: $LOG_FILE"
echo "Press Ctrl+C to stop"
echo ""

# Create file if it doesn't exist
touch "$LOG_FILE"

# Tail the file
tail -f "$LOG_FILE"
