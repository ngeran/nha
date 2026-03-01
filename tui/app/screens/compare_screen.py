"""
Compare Screen - Compare two routing tables with smart anomaly detection.
"""

from pathlib import Path
from typing import Optional, List, Dict, Set

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Vertical, Horizontal
from textual.widgets import (
    Header,
    Footer,
    Static,
    DataTable,
    Button,
    Select,
)
from textual.reactive import reactive

from shared.diff_engine import DiffEngine, DiffResult, SEVERITY_ORDER
from shared.rib_loader import RIBLoader
from shared.anomaly_detection_engine import AnomalyDetectionEngine, Anomaly, AnomalyType


class CompareScreen(Screen):
    CSS = """
    CompareScreen {
        background: #1a1b26;
    }

    Header {
        dock: top;
        height: 1;
        background: #24283b;
        color: #c0caf5;
    }

    Footer {
        dock: bottom;
        height: 1;
        background: #24283b;
    }

    #compare-container {
        padding: 1;
    }

    #form-row {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: #24283b;
    }

    #form-row Horizontal {
        height: auto;
        align: center middle;
    }

    .form-label {
        color: #a9b1d6;
        width: auto;
        margin-right: 1;
    }

    Select {
        width: 32;
        background: #1a1b26;
        border: solid #3b4261;
    }

    Select:focus {
        border: solid #7aa2f7;
    }

    #btn-compare {
        width: 12;
        margin-left: 2;
        background: #7aa2f7;
        color: #1a1b26;
        text-style: bold;
    }

    #btn-compare:hover {
        background: #9aa5ce;
    }

    #btn-compare:disabled {
        background: #3b4261;
        color: #565f89;
    }

    #smart-filters {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: #1f2335;
    }

    .filter-section-label {
        color: #565f89;
        margin-bottom: 1;
    }

    #filter-chips {
        height: auto;
    }

    .chip {
        min-width: 6;
        height: 1;
        background: #24283b;
        color: #9aa5ce;
        border: none;
        padding: 0 1;
        margin-right: 1;
        margin-bottom: 1;
    }

    .chip:hover {
        background: #3b4261;
        color: #c0caf5;
    }

    .chip.active {
        background: #7aa2f7;
        color: #1a1b26;
        text-style: bold;
    }

    .chip.has-items {
        color: #c0caf5;
    }

    .chip.critical {
        border-left: solid #f7768e;
    }

    .chip.warning {
        border-left: solid #e0af68;
    }

    .chip.info {
        border-left: solid #7aa2f7;
    }

    #summary-row {
        height: 1;
        margin-bottom: 1;
    }

    #summary-text {
        color: #9aa5ce;
    }

    #results-table {
        height: 1fr;
    }

    DataTable {
        background: #1a1b26;
    }

    DataTable > .datatable--header {
        background: #24283b;
        color: #7aa2f7;
    }

    DataTable > .datatable--cursor {
        background: #3b4261;
    }

    DataTable > .datatable--hover {
        background: #292e42;
    }
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("c", "run_compare", "Compare"),
        ("r", "reset_filters", "Reset"),
    ]

    file1: reactive[str] = reactive("")
    file2: reactive[str] = reactive("")
    active_filter: reactive[str] = reactive("all")
    diffs: reactive[List[DiffResult]] = reactive(list)
    filtered_diffs: reactive[List[DiffResult]] = reactive(list)
    devices: reactive[List[str]] = reactive(list)
    anomalies: reactive[List[Anomaly]] = reactive(list)

    FILTER_CATEGORIES = {
        "all": ("All", ""),
        "anomalies": ("Anomalies", "critical"),
        "missing": ("Missing", "critical"),
        "failover": ("Failover", "critical"),
        "as_path": ("AS Path", "warning"),
        "next_hop": ("Next-Hop", "critical"),
        "protocol": ("Protocol", "critical"),
        "bgp_attrs": ("BGP Attrs", "warning"),
    }

    def __init__(self, rib_loader: RIBLoader):
        super().__init__()
        self.rib_loader = rib_loader
        self.diff_engine = DiffEngine()
        self.anomaly_engine = AnomalyDetectionEngine()
        self.available_tables: List[str] = []
        self.files: List = []
        self.filter_counts: Dict[str, int] = {}
        self.anomaly_report = None
        self._chips_built = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="compare-container"):
            with Vertical(id="form-row"):
                with Horizontal():
                    yield Static("File 1:", classes="form-label")
                    yield Select([], id="select-file1", prompt="Select file...")
                    yield Static("  File 2:", classes="form-label")
                    yield Select([], id="select-file2", prompt="Select file...")
                    yield Button("Compare", id="btn-compare", disabled=True)

            with Vertical(id="smart-filters"):
                yield Static("FILTERS", classes="filter-section-label")
                with Horizontal(id="filter-chips"):
                    pass

            with Horizontal(id="summary-row"):
                yield Static("Select two files and press Compare", id="summary-text")

            yield DataTable(id="results-table", cursor_type="row", zebra_stripes=True)

        yield Footer()

    def on_mount(self) -> None:
        self._load_files()
        self._setup_results_table()
        self._build_filter_chips()

    def _load_files(self) -> None:
        self.files = self.rib_loader.list_files()
        file_options = [(f.name, f.name) for f in self.files]

        select1 = self.query_one("#select-file1", Select)
        select2 = self.query_one("#select-file2", Select)

        select1.set_options(file_options)
        select2.set_options(file_options)

    def _setup_results_table(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()
        if not table.columns:
            table.add_columns("Sev", "Table", "Prefix", "Category", "Field")

    def _build_filter_chips(self) -> None:
        chips_container = self.query_one("#filter-chips", Horizontal)

        chips_container.remove_children()
        self._chips_built = False

        for filter_key, (label, severity) in self.FILTER_CATEGORIES.items():
            count = self.filter_counts.get(filter_key, 0)
            display_label = f"{label}"
            if count > 0:
                display_label = f"{label} [{count}]"

            chip = Button(display_label, classes=f"chip {severity}")
            chip.filter_key = filter_key
            if self.active_filter == filter_key:
                chip.add_class("active")
            if count > 0:
                chip.add_class("has-items")
            chips_container.mount(chip)

        self._chips_built = True

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "select-file1":
            self.file1 = event.value or ""
        elif event.select.id == "select-file2":
            self.file2 = event.value or ""

        self._update_compare_button()

    def _update_compare_button(self) -> None:
        btn = self.query_one("#btn-compare", Button)
        btn.disabled = not (self.file1 and self.file2 and self.file1 != self.file2)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button

        if btn.id == "btn-compare":
            self.action_run_compare()
        elif hasattr(btn, "filter_key"):
            self._set_filter(btn.filter_key)

    def _set_filter(self, filter_key: str) -> None:
        if self.active_filter == filter_key:
            self.active_filter = "all"
        else:
            self.active_filter = filter_key
        self._apply_filters()

    def action_run_compare(self) -> None:
        if not self.file1 or not self.file2:
            self.notify("Select two files", severity="warning")
            return

        if self.file1 == self.file2:
            self.notify("Select different files", severity="warning")
            return

        self.diff_engine = DiffEngine()

        file1_path = self.rib_loader.data_dir / self.file1
        file2_path = self.rib_loader.data_dir / self.file2

        if not self.diff_engine.load_file(file1_path):
            self.notify(f"Failed to load {self.file1}", severity="error")
            return

        if not self.diff_engine.load_file(file2_path):
            self.notify(f"Failed to load {self.file2}", severity="error")
            return

        self.devices = self.diff_engine.get_loaded_devices()
        self.available_tables = self.diff_engine.get_available_tables()

        self.diffs = self.diff_engine.compare(include_inactive=True)

        self.anomaly_engine = AnomalyDetectionEngine()
        self.anomaly_report = self.anomaly_engine.analyze(self.diffs, self.devices)
        self.anomalies = self.anomaly_report.anomalies

        self._calculate_filter_counts()
        self._apply_filters()

    def _calculate_filter_counts(self) -> None:
        self.filter_counts = {"all": len(self.diffs)}

        for diff in self.diffs:
            cat = diff.category.lower().replace("-", "_")
            field = diff.field.lower().replace("-", "_").replace(" ", "_")

            if cat == "presence":
                self.filter_counts["missing"] = self.filter_counts.get("missing", 0) + 1
            elif cat == "next_hop" or "gateway" in field:
                self.filter_counts["next_hop"] = (
                    self.filter_counts.get("next_hop", 0) + 1
                )
            elif cat == "protocol":
                if "protocol" in field:
                    self.filter_counts["protocol"] = (
                        self.filter_counts.get("protocol", 0) + 1
                    )
            elif cat == "bgp":
                self.filter_counts["bgp_attrs"] = (
                    self.filter_counts.get("bgp_attrs", 0) + 1
                )
                if "as_path" in field:
                    self.filter_counts["as_path"] = (
                        self.filter_counts.get("as_path", 0) + 1
                    )

        if self.anomaly_report:
            self.filter_counts["anomalies"] = self.anomaly_report.total_anomalies
            self.filter_counts["failover"] = len(
                [
                    a
                    for a in self.anomalies
                    if a.anomaly_type == AnomalyType.ROUTE_FAILOVER
                ]
            )

        self._build_filter_chips()

    def _apply_filters(self) -> None:
        if self.active_filter == "all":
            self.filtered_diffs = self.diffs
        elif self.active_filter == "anomalies":
            seen = set()
            self.filtered_diffs = []
            for anomaly in self.anomalies:
                for diff in anomaly.related_diffs:
                    diff_id = id(diff)
                    if diff_id not in seen:
                        seen.add(diff_id)
                        self.filtered_diffs.append(diff)
        else:
            self.filtered_diffs = []
            for diff in self.diffs:
                if self._matches_filter(diff):
                    self.filtered_diffs.append(diff)

        self._update_results()
        self._build_filter_chips()

    def _matches_filter(self, diff: DiffResult) -> bool:
        cat = diff.category.lower().replace("-", "_")
        field = diff.field.lower().replace("-", "_").replace(" ", "_")

        if self.active_filter == "missing":
            return cat == "presence"
        elif self.active_filter == "failover":
            return (cat == "next_hop" or "gateway" in field) or "origin" in field
        elif self.active_filter == "as_path":
            return "as_path" in field
        elif self.active_filter == "next_hop":
            return cat == "next_hop" or "gateway" in field
        elif self.active_filter == "protocol":
            return cat == "protocol"
        elif self.active_filter == "bgp_attrs":
            return cat == "bgp"

        return True

    def _update_results(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()

        columns = ["Sev", "Table", "Prefix", "Category", "Field"] + self.devices
        table.columns.clear()
        for col in columns:
            table.add_column(col)

        for diff in self.filtered_diffs:
            table.add_row(*diff.to_row(self.devices))

        summary = self.diff_engine.get_summary(self.diffs)
        sev = summary.by_severity

        filter_label = self.FILTER_CATEGORIES.get(self.active_filter, ("All", ""))[0]

        anomaly_count = len(self.anomalies) if self.anomalies else 0
        anomaly_text = (
            f"Anomalies: [#ff9e64]{anomaly_count}[/] | " if anomaly_count > 0 else ""
        )

        summary_text = (
            f"{anomaly_text}"
            f"Showing [#7aa2f7]{len(self.filtered_diffs)}[/]/[#ff9e64]{len(self.diffs)}[/] "
            f"[#565f89]({filter_label})[/] | "
            f"Crit: [#f7768e]{sev.get('CRITICAL', 0)}[/] | "
            f"High: [#ff9e64]{sev.get('HIGH', 0)}[/] | "
            f"Med: [#e0af68]{sev.get('MEDIUM', 0)}[/] | "
            f"Low: [#7aa2f7]{sev.get('LOW', 0)}[/]"
        )
        self.query_one("#summary-text", Static).update(summary_text)

    def action_reset_filters(self) -> None:
        self.active_filter = "all"
        if self.diffs:
            self._apply_filters()
        self.notify("Filters reset", severity="information")
