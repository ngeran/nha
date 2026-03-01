# RIB Monitor - Native Development Setup

This document describes how to run RIB Monitor natively on your machine with text-based navigation.

## Quick Start

```bash
# 1. Setup the development environment
python3 setup.py

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Run the application
./run-native.sh
```

## Text-Based Navigation

The application now uses text-based navigation indicators instead of buttons:

### Navigation Bar
```
NAVIGATION
────────────────────────────
[ d ] Dashboard
[ t ] RIB Table
[ i ] Import/Export
[ c ] Disconnect
[ r ] Refresh
[ q ] Quit
────────────────────────────
```

### Status Indicators
```
STATUS
────────────────────────────
Device:     Disconnected
WebSocket:   Disconnected
Routes:     0
Anomalies:   0
────────────────────────────
```

## Key Features

- **Clean text interface** - No large buttons, compact navigation
- **Real-time status** - Shows device and WebSocket connection status
- **Hotkey navigation** - Single character commands for all actions
- **Starts blank** - No initial connections
- **Import/Export** - Support for XML, JSON, YAML formats
- **Dashboard view** - Welcome screen with feature overview
- **Table view** - Interactive routing table with row selection
- **Detail view** - Press Enter on any route to see full details

## Supported Formats

### XML
```xml
<routes>
    <route prefix="10.0.0.0/24" table="inet.0" protocol="BGP">
        <next-hop>192.168.1.1</next-hop>
        <age>3600</age>
    </route>
</routes>
```

### JSON
```json
{
    "routes": [
        {
            "prefix": "10.0.0.0/24",
            "table": "inet.0",
            "protocol": "BGP",
            "next-hop": "192.168.1.1",
            "age": 3600
        }
    ]
}
```

### YAML
```yaml
routes:
  - prefix: 10.0.0.0/24
    table: inet.0
    protocol: BGP
    next-hop: 192.168.1.1
    age: 3600
```

## Key Bindings

| Key | Action | Status |
|-----|---------|--------|
| D | Dashboard view | Available |
| T | RIB Table view | Available |
| I | Import/Export routes | Available |
| C | Disconnect from device | Available only when connected |
| R | Refresh routes | Available only when connected |
| Q | Quit application | Available |
| Enter | View route details | Available on table rows |
| Escape | Close modal/popup | Available |

## File Structure

```
rib-monitor/
├── .venv/                 # Python virtual environment
├── rib-data/               # Data directory
│   ├── baseline-routes.xml   # XML baseline
│   ├── baseline-routes.json  # JSON baseline  
│   └── baseline-routes.yaml  # YAML baseline
├── shared/
│   └── data_manager.py    # Import/export logic
├── tui/app/screens/
│   └── import_export.py  # Import/export UI
├── setup.py                # Environment setup
├── run.py                  # Python application launcher
└── run-native.sh           # Bash launcher with welcome screen
```

## Development Notes

- Runs completely natively (no Docker)
- WebSocket connection to backend at http://localhost:8000
- Routes are cached locally for performance
- Real-time updates via WebSocket when connected
- Compact text-based interface for power users
- Baseline storage in `rib-data/` directory