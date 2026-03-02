"""
Dashboard widget for displaying baseline routing table statistics
"""

from textual.widget import Widget
from textual.containers import Vertical, Horizontal, Grid
from textual.widgets import Static, Button
from textual.reactive import reactive
from textual.app import ComposeResult
from pathlib import Path
from typing import Optional, Dict, List

from shared.config import ConfigManager, BaselineConfig
from shared.rib_reader import RIBReader
from shared.analysis_engine import AnalysisEngine


class DashboardWidget(Widget):
    """Dashboard widget displaying baseline routing table statistics"""

    DEFAULT_CSS = """
    DashboardWidget {
        height: auto;
        margin: 1 0;
    }
    
    .dashboard-title {
        text-align: center;
        color: #7aa2f7;
        text-style: bold;
        background: #1f2335;
        padding: 0 2;
        height: 1;
        margin-bottom: 1;
    }
    
    .dashboard-grid {
        grid-size: 4;
        grid-gutter: 1;
        padding: 0 1;
        height: auto;
    }
    
    .stat-card {
        background: #24283b;
        border: solid #3b4261;
        padding: 1;
        height: auto;
    }
    
    .stat-title {
        color: #565f89;
        text-style: bold;
        margin-bottom: 1;
    }
    
    .stat-value {
        color: #9aa5ce;
        text-style: bold;
    }
    
    .stat-subtitle {
        color: #565f89;
    }
    
    .baseline-info {
        text-align: center;
        color: #565f89;
        background: #1f2335;
        padding: 0 2;
        height: 1;
        margin-top: 1;
    }
    
    .set-baseline-btn {
        color: #7aa2f7;
        background: #24283b;
        border: solid #3b4261;
        padding: 0 1;
        margin: 1;
    }
    
    .set-baseline-btn:hover {
        color: #c0caf5;
        background: #3b4261;
    }
    """

    baseline_config = reactive(None)

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.baseline_stats = {}

    def compose(self) -> ComposeResult:
        # Load baseline configuration
        self.baseline_config = self.config_manager.load_baseline_config()

        yield Static("BASELINE STATISTICS", classes="dashboard-title")

        if not self.baseline_config:
            yield Static(
                "No baseline configured. Press 'b' to set baseline.",
                classes="baseline-info",
            )
            return

        # Display baseline information
        baseline_info = f"Baseline: {self.baseline_config.device_name}"
        if self.baseline_config.description:
            baseline_info += f" - {self.baseline_config.description}"
        yield Static(baseline_info, classes="baseline-info")

        # Load and display baseline statistics
        stats = self._load_baseline_stats()
        if stats:
            with Grid(classes="dashboard-grid"):
                # Total Routes
                with Vertical(classes="stat-card"):
                    yield Static("Total Routes", classes="stat-title")
                    yield Static(
                        str(stats.get("total_routes", 0)), classes="stat-value"
                    )
                    yield Static("All protocols", classes="stat-subtitle")

                # Active Routes
                with Vertical(classes="stat-card"):
                    yield Static("Active Routes", classes="stat-title")
                    yield Static(
                        str(stats.get("active_routes", 0)), classes="stat-value"
                    )
                    yield Static("Reachable", classes="stat-subtitle")

                # BGP Routes
                with Vertical(classes="stat-card"):
                    yield Static("BGP Routes", classes="stat-title")
                    yield Static(str(stats.get("bgp_routes", 0)), classes="stat-value")
                    yield Static("External", classes="stat-subtitle")

                # Unique Origins
                with Vertical(classes="stat-card"):
                    yield Static("Origin ASNs", classes="stat-title")
                    yield Static(
                        str(stats.get("unique_origins", 0)), classes="stat-value"
                    )
                    yield Static("AS numbers", classes="stat-subtitle")

                # Top 5 Origin ASNs
                if "top_origins" in stats and stats["top_origins"]:
                    top_origins_text = "\\n".join(
                        [f"{asn}: {count}" for asn, count in stats["top_origins"][:5]]
                    )
                    with Vertical(classes="stat-card"):
                        yield Static("Top Origin ASNs", classes="stat-title")
                        yield Static("", classes="stat-value")
                        yield Static(top_origins_text, classes="stat-subtitle")

                # Top 5 Transit ASNs
                if "top_transit" in stats and stats["top_transit"]:
                    top_transit_text = "\\n".join(
                        [f"{asn}: {count}" for asn, count in stats["top_transit"][:5]]
                    )
                    with Vertical(classes="stat-card"):
                        yield Static("Top Transit ASNs", classes="stat-title")
                        yield Static("", classes="stat-value")
                        yield Static(top_transit_text, classes="stat-subtitle")

    def _load_baseline_stats(self) -> Optional[Dict]:
        """Load baseline statistics"""
        if not self.baseline_config:
            return None

        baseline_path = self.config_manager.get_baseline_path()
        if not baseline_path or not baseline_path.exists():
            return None

        try:
            reader = RIBReader()
            if not reader.read_file(baseline_path):
                return None

            routes = reader.get_routes()
            summary = reader.get_summary()
            analysis = AnalysisEngine().analyze(routes)

            stats = {
                "total_routes": summary.get("total_routes", 0),
                "active_routes": summary.get("active_routes", 0),
                "bgp_routes": getattr(analysis, "bgp_routes", 0),
                "unique_origins": getattr(analysis.as_path_stats, "unique_origins", 0)
                if hasattr(analysis, "as_path_stats")
                else 0,
                "top_origins": getattr(analysis, "top_origins", [])[:5],
                "top_transit": getattr(analysis, "top_transit", [])[:5],
            }

            return stats
        except Exception as e:
            print(f"Error loading baseline stats: {e}")
            return None

    def refresh_baseline(self) -> None:
        """Refresh baseline statistics"""
        self.baseline_config = self.config_manager.load_baseline_config()
        self.query("*").remove()
        self.compose()
