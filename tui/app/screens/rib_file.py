"""
RIB File Viewer Screen - Displays routing table from a file with filtering and analysis.
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
    Input,
    Button,
)
from textual.reactive import reactive
from .detail import RouteDetailScreen


class RIBFileScreen(Screen):
    CSS = """
    Screen {
        background: #1a1b26;
        layout: vertical;
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

    #rib-file-container {
        padding: 0;
        height: 100%;
        overflow-y: auto;
    }

    #rib-file-header {
        text-align: center;
        background: #24283b;
        color: #c0caf5;
        text-style: bold;
        padding: 0 2;
    }

    #rib-summary-text {
        color: #9aa5ce;
        background: #1f2335;
        padding: 0 2;
        text-align: center;
        height: 1;
    }

    #analysis-row {
        background: #1f2335;
        height: 3;
        padding: 0 2;
        margin-top: 1;
        margin-bottom: 1;
    }

    #analysis-row-1, #analysis-row-2 {
        height: 1;
    }

    .chip-sep {
        color: #3b4261;
        margin-right: 1;
    }
    
    .sep {
        color: #565f89;
        margin: 0 1;
    }
    
    #filter-spacer, #filter-spacer2 {
        height: 1;
    }

    .chip {
        min-width: 5;
        height: 1;
        background: transparent;
        color: #9aa5ce;
        border: none;
        padding: 0 1;
        margin-right: 0;
    }

    .chip:hover {
        color: #c0caf5;
        background: #3b4261;
    }

    .chip.active {
        color: #7aa2f7;
        text-style: bold;
        background: #3b4261;
    }

    .chip.info {
        color: #7aa2f7;
    }

    .chip.warning {
        color: #e0af68;
    }

    .chip.critical {
        color: #f7768e;
    }

    .filter-row {
        background: #16161e;
        padding: 0 2;
        height: 5;
        margin: 1 0;
        align: left middle;
        border-top: solid #565f89;
        border-bottom: solid #565f89;
    }

    .filter-label {
        color: #9aa5ce;
        width: auto;
        margin-right: 1;
        text-style: bold;
    }

    #filter-prefix {
        width: 20;
        height: 1;
        background: #24283b;
        color: #c0caf5;
        border: solid #565f89;
    }

    #btn-all.active, #btn-active.active, #btn-inactive.active,
    #btn-protocol.active, #btn-table.active {
        background: #7aa2f7;
        color: #1a1b26;
    }

    .filter-btn {
        width: 10;
        height: 1;
        background: #24283b;
        color: #9aa5ce;
        border: solid #565f89;
        text-align: center;
        text-style: bold;
    }
    
    .filter-btn:hover {
        background: #3b4261;
        color: #c0caf5;
    }

    DataTable {
        height: 1fr;
        width: 100%;
        min-height: 10;
    }

    .data-table {
        height: 1fr;
        width: 100%;
    }
    """

    BINDINGS = [
        ("c", "connect", "Connect"),
        ("d", "disconnect", "Disconnect"),
        ("x", "show_compare", "Compare"),
        ("i", "show_import", "Import"),
        ("e", "show_export", "Export"),
        ("f", "focus_filter", "Filter"),
        ("r", "reset_filters", "Reset"),
        ("q", "app.quit", "Back"),
        ("enter", "show_route_details", "Route Details"),
        ("esc", "app.pop_screen", "Back"),
    ]

    filter_protocol = reactive("")
    protocol_filter = reactive("")
    filter_active = reactive("all")
    filter_prefix = reactive("")
    filter_table = reactive("")
    analysis_filters = reactive(set())
    origin_filter = reactive("")
    transit_filter = reactive("")
    peer_filter = reactive("")

    def __init__(self, file_path: Path, file_name: str = ""):
        super().__init__()
        self.file_path = Path(file_path)
        self.file_name = file_name or self.file_path.name
        self.all_routes: List = []
        self.protocols: Dict[str, int] = {}
        self.tables: Dict[str, int] = {}
        self.metadata = {}
        self.analysis_report = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="rib-file-container"):
            yield Static(self._get_header_text(), id="rib-file-header")
            yield Static("", id="rib-summary-text")

            with Vertical(id="analysis-row"):
                with Horizontal(id="analysis-row-1"):
                    pass
                with Horizontal(id="analysis-row-2"):
                    pass

            yield Static("", id="filter-spacer")
            with Horizontal(classes="filter-row"):
                yield Static("Filter:", classes="filter-label")
                yield Input(placeholder="prefix...", id="filter-prefix")
                yield Static("  ", classes="sep")
                yield Button("all", id="btn-all", classes="filter-btn active")
                yield Static("|", classes="sep")
                yield Button("active", id="btn-active", classes="filter-btn")
                yield Static("|", classes="sep")
                yield Button("inactive", id="btn-inactive", classes="filter-btn")
                yield Static("|", classes="sep")
                yield Button("protocol", id="btn-protocol", classes="filter-btn")
                yield Static("|", classes="sep")
                yield Button("table", id="btn-table", classes="filter-btn")
            yield Static("", id="filter-spacer2")

            yield DataTable(id="rib-file-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def _get_header_text(self) -> str:
        return f"[bold #c0caf5]Routing Table:[/bold #c0caf5] {self.file_name}"

    def on_mount(self) -> None:
        from shared.rib_reader import RIBReader
        from shared.analysis_engine import AnalysisEngine

        reader = RIBReader()

        if reader.read_file(self.file_path):
            self.all_routes = reader.get_routes()
            self.metadata = reader.get_metadata()

            # Check if we have any routes
            if not self.all_routes:
                summary_text = "[red]No routes found in file[/red]"
                self.query_one("#rib-summary-text", Static).update(summary_text)

                # Still set up the table with empty data
                table = self.query_one("#rib-file-table", DataTable)
                table.clear()
                table.add_columns(
                    "*", "Prefix", "Table", "Protocol", "Next Hop", "Pref", "AS Path"
                )

                # Show a message in the analysis row
                row1 = self.query_one("#analysis-row-1", Horizontal)
                row1.remove_children()
                row1.mount(Static("No routes to analyze", classes="chip info"))
                return

            summary = reader.get_summary()
            self.protocols = summary.get("protocols", {})
            self.tables = {}
            for route in self.all_routes:
                table_name = route.table
                self.tables[table_name] = self.tables.get(table_name, 0) + 1

            engine = AnalysisEngine()
            self.analysis_report = engine.analyze(self.all_routes)
            self._build_analysis_chips()

            summary_text = (
                f"Device: [#7dcfff]{summary.get('hostname', 'N/A')}[/] | "
                f"Routes: [#73daca]{summary.get('total_routes', 0)}[/] | "
                f"Active: [#e0af68]{summary.get('active_routes', 0)}[/] | "
                f"Origins: [#bb9af7]{self.analysis_report.as_path_stats.unique_origins}[/] | "
                f"Format: [#7dcfff]{summary.get('format', 'N/A')}[/]"
            )
            self.query_one("#rib-summary-text", Static).update(summary_text)

            # Schedule table population for after the screen is rendered
            self.call_after_refresh(self._populate_table)
        else:
            self.query_one("#rib-summary-text", Static).update(
                "[red]Error loading file[/red]"
            )

    def _populate_table(self) -> None:
        """Populate the table with route data after the screen is ready."""
        try:
            # Get the table widget
            table = self.query_one("#rib-file-table", DataTable)

            # Apply filters - this will also set up the table columns
            self._apply_filters()

            # Ensure the table is properly displayed
            table.display = True

            # Focus on table so users can immediately select rows
            table.focus()
        except Exception as e:
            # If there's an error, try again in a moment
            self.call_after_refresh(self._populate_table)

    def _build_analysis_chips(self) -> None:
        if not self.analysis_report:
            # Show a message when no analysis data is available
            row1 = self.query_one("#analysis-row-1", Horizontal)
            row2 = self.query_one("#analysis-row-2", Horizontal)
            row1.mount(Static("No analysis data available", classes="chip info"))
            return

        row1 = self.query_one("#analysis-row-1", Horizontal)
        row2 = self.query_one("#analysis-row-2", Horizontal)
        row1.remove_children()
        row2.remove_children()

        r = self.analysis_report

        # Row 1: BGP, Origin AS, Transit AS, Peers
        row1_chips = [
            ("bgp", f"BGP:{r.bgp_routes}", "info"),
        ]

        # Show top 5 origins instead of 2
        for origin_as, count in r.top_origins[:5]:
            row1_chips.append((f"origin_{origin_as}", f"O{origin_as}:{count}", "info"))

        # Show top 3 transit ASes instead of 2
        for transit_as, count in r.top_transit[:3]:
            row1_chips.append(
                (f"transit_{transit_as}", f"T{transit_as}:{count}", "warning")
            )

        # Show top 3 peers instead of 2
        for peer, count in r.top_peers[:3]:
            short_peer = peer.split(".")[-1] if "." in peer else peer[:8]
            row1_chips.append((f"peer_{peer}", f"P{short_peer}:{count}", "info"))

        if r.self_originated and r.self_originated.count > 0:
            row1_chips.append(
                ("self_orig", f"Self:{r.self_originated.count}", "warning")
            )

        # Row 2: Attributes, Age, Prefix, Coverage
        row2_chips = []

        if r.non_default_lp and len(r.non_default_lp) > 0:
            row2_chips.append(("non_def_lp", f"LP:{len(r.non_default_lp)}", "critical"))

        if r.non_default_med and len(r.non_default_med) > 0:
            row2_chips.append(
                ("non_def_med", f"MED:{len(r.non_default_med)}", "warning")
            )

        if r.with_communities and len(r.with_communities) > 0:
            row2_chips.append(
                ("communities", f"Comm:{len(r.with_communities)}", "info")
            )

        if r.prepending_count > 0:
            row2_chips.append(("prepending", f"Prep:{r.prepending_count}", "warning"))

        if r.route_age_stats.routes_under_1hr > 0:
            row2_chips.append(
                ("new_routes", f"New:{r.route_age_stats.routes_under_1hr}", "critical")
            )

        if r.route_age_stats.routes_over_1day > 0:
            row2_chips.append(
                ("stable", f"Stable:{r.route_age_stats.routes_over_1day}", "info")
            )

        if r.specific_routes_count > 0:
            row2_chips.append(
                ("specific", f"Spec:{r.specific_routes_count}", "warning")
            )

        if r.aggregate_routes_count > 0:
            row2_chips.append(("aggregate", f"Agg:{r.aggregate_routes_count}", "info"))

        if r.prefix_coverage.rfc1918_count > 0:
            row2_chips.append(
                ("rfc1918", f"Priv:{r.prefix_coverage.rfc1918_count}", "warning")
            )

        if r.prefix_coverage.bogon_count > 0:
            row2_chips.append(
                ("bogon", f"Bogon:{r.prefix_coverage.bogon_count}", "critical")
            )

        if not r.prefix_coverage.has_default_ipv4:
            row2_chips.append(("no_default", "NoDef!", "critical"))

        # Add protocol breakdown chips
        for protocol, count in sorted(
            self.protocols.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            row2_chips.append(
                (f"proto_{protocol.lower()}", f"{protocol}:{count}", "info")
            )

        # Mount chips with "|" separator
        self._mount_chips_with_separators(row1, row1_chips)
        self._mount_chips_with_separators(row2, row2_chips)

    def _mount_chips_with_separators(
        self, container: Horizontal, chips_data: List
    ) -> None:
        first = True
        for key, label, severity in chips_data:
            # Add separator before chip (except for first one)
            if not first:
                sep = Static("|", classes="chip-sep")
                container.mount(sep)
            first = False

            # Replace dots with underscores to create valid IDs
            safe_key = key.replace(".", "_").replace("-", "_")
            chip = Button(label, classes=f"chip {severity}", id=f"analysis-{safe_key}")
            is_active = (
                key in self.analysis_filters
                or (key.startswith("origin_") and key == f"origin_{self.origin_filter}")
                or (
                    key.startswith("transit_")
                    and key == f"transit_{self.transit_filter}"
                )
                or (key.startswith("peer_") and key == f"peer_{self.peer_filter}")
                or (key.startswith("proto_") and key == f"proto_{self.protocol_filter}")
            )
            if is_active:
                chip.add_class("active")

            container.mount(chip)

    def _apply_filters(self) -> None:
        filtered = []
        table = self.query_one("#rib-file-table", DataTable)

        self_originated_prefixes: Set[str] = set()
        non_default_lp_prefixes: Set[str] = set()
        non_default_med_prefixes: Set[str] = set()
        community_prefixes: Set[str] = set()

        if self.analysis_report:
            if self.analysis_report.self_originated:
                self_originated_prefixes = set(
                    self.analysis_report.self_originated.prefixes
                )
            for anomaly in self.analysis_report.non_default_lp:
                non_default_lp_prefixes.add(anomaly.prefix)
            for anomaly in self.analysis_report.non_default_med:
                non_default_med_prefixes.add(anomaly.prefix)
            for anomaly in self.analysis_report.with_communities:
                community_prefixes.add(anomaly.prefix)

        for route in self.all_routes:
            if (
                self.filter_prefix
                and self.filter_prefix.lower() not in route.prefix.lower()
            ):
                continue

            if (
                self.filter_protocol
                and route.protocol.upper() != self.filter_protocol.upper()
            ):
                continue

            if (
                self.protocol_filter
                and route.protocol.upper() != self.protocol_filter.upper()
            ):
                continue

            if self.filter_table and route.table != self.filter_table:
                continue

            if self.filter_active == "active" and not route.active:
                continue
            if self.filter_active == "inactive" and route.active:
                continue

            if self.analysis_filters:
                if "self_orig" in self.analysis_filters:
                    if route.prefix not in self_originated_prefixes:
                        continue
                if "non_def_lp" in self.analysis_filters:
                    if route.prefix not in non_default_lp_prefixes:
                        continue
                if "non_def_med" in self.analysis_filters:
                    if route.prefix not in non_default_med_prefixes:
                        continue
                if "communities" in self.analysis_filters:
                    if route.prefix not in community_prefixes:
                        continue
                if "bgp" in self.analysis_filters:
                    if route.protocol.upper() != "BGP":
                        continue
                if "prepending" in self.analysis_filters:
                    as_path = (route.as_path or "").strip()
                    tokens = [
                        t
                        for t in as_path.split()
                        if t not in ("I", "E", "?", "Aggregated")
                    ]
                    # Count consecutive occurrences
                    for i, token in enumerate(tokens[:-1]):
                        if tokens[i + 1] == token:
                            continue

                if "new_routes" in self.analysis_filters:
                    if route.age < 3600:  # 1 hour in seconds
                        continue

                if "stable" in self.analysis_filters:
                    if route.age < 86400:  # 1 day in seconds
                        continue

                if "specific" in self.analysis_filters:
                    # Could check for specific patterns in prefix
                    pass

                if "aggregate" in self.analysis_filters:
                    # Could check for aggregated prefixes
                    pass

                if "rfc1918" in self.analysis_filters:
                    if self._is_rfc1918(route.prefix):
                        continue

                if "bogon" in self.analysis_filters:
                    if self._is_bogon(route.prefix):
                        continue

                if "no_default" in self.analysis_filters:
                    # Check if prefix is not a default route
                    if not (route.prefix == "0.0.0.0/0" or route.prefix == "::/0"):
                        continue

                # If we get here, the route passes all filters
                filtered.append(route)

        # Clear the table completely
        table.clear()

        # Re-add columns (clear() removes them)
        columns = ["Act", "Prefix", "Table", "Protocol", "Next-Hop", "Pref", "AS Path"]
        table.add_columns(*columns)

        # Apply filters and add routes
        for route in self.all_routes:
            # Prefix filter
            if (
                self.filter_prefix
                and self.filter_prefix.lower() not in route.prefix.lower()
            ):
                continue

            # Active filter
            if self.filter_active == "active" and not route.active:
                continue
            if self.filter_active == "inactive" and route.active:
                continue

            # Protocol filter
            if (
                self.protocol_filter
                and route.protocol.upper() != self.protocol_filter.upper()
            ):
                continue

            # Table filter
            if self.filter_table and route.table != self.filter_table:
                continue

            # Analysis filters
            if self.analysis_filters:
                # Simple analysis filter checks
                if "bgp" in self.analysis_filters and route.protocol.upper() != "BGP":
                    continue

            # If we get here, the route passes all filters
            filtered.append(route)

        # Add filtered routes
        for route in filtered:
            row_data = route.to_table_row()
            table.add_row(*row_data)

        # Ensure the table is refreshed
        table.refresh()

        # Force a repaint
        table._size = table._size  # Trigger size recalculation

    def action_focus_filter(self) -> None:
        """Focus on the prefix filter input."""
        self.query_one("#filter-prefix", Input).focus()

    def action_reset_filters(self) -> None:
        """Reset all filters to default values."""
        self.filter_prefix = ""
        self.filter_active = "all"
        self.protocol_filter = ""
        self.filter_table = ""
        self.analysis_filters = set()
        self.origin_filter = ""
        self.transit_filter = ""
        self.peer_filter = ""

        # Update UI elements
        self.query_one("#filter-prefix", Input).value = ""
        self._update_active_buttons("btn-all")

        # Re-apply filters
        self._apply_filters()

        self.notify("Filters reset", severity="information")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-prefix":
            self.filter_prefix = event.value
            self._apply_filters()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button
        btn_id = btn.id

        if btn_id == "btn-all":
            self.filter_active = "all"
            self._update_active_buttons("btn-all")
        elif btn_id == "btn-active":
            self.filter_active = "active"
            self._update_active_buttons("btn-active")
        elif btn_id == "btn-inactive":
            self.filter_active = "inactive"
            self._update_active_buttons("btn-inactive")
        elif btn_id == "btn-protocol":
            self._cycle_protocol()
        elif btn_id == "btn-table":
            self._cycle_table()
        elif btn_id == "btn-test-details":
            self._show_test_details()
        elif btn.id and btn.id.startswith("analysis-"):
            analysis_key = (
                btn.id.replace("analysis-", "", 1).replace("_", ".").replace("_", "-")
            )
            self._toggle_analysis_filter(analysis_key)

        self._apply_filters()

    def _update_analysis_filters(self) -> None:
        """Update analysis filters based on current filter states."""
        filters = set()

        if self.origin_filter:
            filters.add(f"origin_{self.origin_filter}")

        if self.transit_filter:
            filters.add(f"transit_{self.transit_filter}")

        if self.peer_filter:
            filters.add(f"peer_{self.peer_filter}")

        if self.protocol_filter:
            filters.add(f"proto_{self.protocol_filter}")

        self.analysis_filters = filters

    def _toggle_analysis_filter(self, analysis_key: str) -> None:
        """Toggle an analysis filter on/off."""
        # Check if this is a special filter that should be exclusive
        if analysis_key.startswith("origin_"):
            asn = analysis_key.replace("origin_", "")
            if self.origin_filter == asn:
                self.origin_filter = ""
            else:
                self.origin_filter = asn
        elif analysis_key.startswith("transit_"):
            asn = analysis_key.replace("transit_", "")
            if self.transit_filter == asn:
                self.transit_filter = ""
            else:
                self.transit_filter = asn
        elif analysis_key.startswith("peer_"):
            peer = analysis_key.replace("peer_", "")
            if self.peer_filter == peer:
                self.peer_filter = ""
            else:
                self.peer_filter = peer
        elif analysis_key.startswith("proto_"):
            proto = analysis_key.replace("proto_", "")
            if self.protocol_filter == proto:
                self.protocol_filter = ""
            else:
                self.protocol_filter = proto
        else:
            # For general filters, just toggle them in the set
            if analysis_key in self.analysis_filters:
                self.analysis_filters.remove(analysis_key)
            else:
                self.analysis_filters.add(analysis_key)

        # Rebuild analysis filters from the reactive attributes
        self._update_analysis_filters()

    def _cycle_protocol(self) -> None:
        """Cycle through available protocols."""
        if not self.protocols:
            return

        protocols = list(self.protocols.keys())
        if not protocols:
            return

        if self.protocol_filter in protocols:
            current_index = protocols.index(self.protocol_filter)
            next_index = (current_index + 1) % len(protocols)
        else:
            next_index = 0

        self.protocol_filter = protocols[next_index]
        self._update_analysis_filters()
        self._build_analysis_chips()
        self._apply_filters()

        # Update protocol button label
        btn = self.query_one("#btn-protocol", Button)
        if self.protocol_filter:
            btn.label = f"{self.protocol_filter}"
        else:
            btn.label = "protocol"

    def _show_test_details(self) -> None:
        """Show test route details."""
        if not self.all_routes:
            return

        # Use first route as a test
        test_route = self.all_routes[0]

        route_dict = {
            "prefix": test_route.prefix,
            "table": test_route.table,
            "protocol": test_route.protocol,
            "next_hop": test_route.next_hop,
            "age": test_route.age,
            "active": test_route.active,
            "attributes": {"protocol": test_route.protocol},
        }

        # Extract protocol-specific attributes
        if test_route.protocol.upper() == "BGP":
            route_dict["attributes"].update(
                {
                    "as_path": test_route.as_path or "N/A",
                    "local_pref": test_route.local_pref or "N/A",
                    "med": test_route.med or "N/A",
                    "communities": getattr(test_route, "communities", []),
                }
            )

        # Show detail screen
        self.app.push_screen(
            RouteDetailScreen(route_dict), callback=self._return_to_rib_screen
        )

    def _return_to_rib_screen(self, result=None) -> None:
        """Callback function to return to RIB screen."""
        pass  # We don't need to do anything, just stay on the current screen

    def _update_active_buttons(self, active_btn_id: str) -> None:
        """Update the visual state of filter buttons."""
        btn_all = self.query_one("#btn-all", Button)
        btn_active = self.query_one("#btn-active", Button)
        btn_inactive = self.query_one("#btn-inactive", Button)

        # Remove active class from all filter buttons
        for btn in [btn_all, btn_active, btn_inactive]:
            btn.remove_class("active")

        # Add active class to the selected button
        if active_btn_id == "btn-all":
            btn_all.add_class("active")
        elif active_btn_id == "btn-active":
            btn_active.add_class("active")
        elif active_btn_id == "btn-inactive":
            btn_inactive.add_class("active")

    def _cycle_table(self) -> None:
        """Cycle through available routing tables."""
        if not self.tables:
            return

        tables = list(self.tables.keys())
        if not tables:
            return

        if self.filter_table in tables:
            current_index = tables.index(self.filter_table)
            next_index = (current_index + 1) % len(tables)
        else:
            next_index = 0

        self.filter_table = tables[next_index]
        self._apply_filters()
        self._update_active_buttons("btn-table")

    def _is_rfc1918(self, prefix: str) -> bool:
        if "/" not in prefix:
            return False
        addr = prefix.split("/")[0]
        if ":" in addr:
            return False
        try:
            parts = [int(p) for p in addr.split(".")]
            if len(parts) != 4:
                return False
            if parts[0] == 10:
                return True
            if parts[0] == 172 and 16 <= parts[1] <= 31:
                return True
            if parts[0] == 192 and parts[1] == 168:
                return True
        except (ValueError, IndexError):
            return False
        return False

    def _is_bogon(self, prefix: str) -> bool:
        if "/" not in prefix:
            return False
        addr = prefix.split("/")[0]
        if ":" in addr:
            return False
        try:
            parts = [int(p) for p in addr.split(".")]
            if len(parts) != 4:
                return False
            if parts[0] == 192 and parts[1] == 0 and parts[2] == 2:
                return True
            if parts[0] == 198 and parts[1] == 51 and parts[2] == 100:
                return True
            if parts[0] == 203 and parts[1] == 0 and parts[2] == 113:
                return True
            if parts[0] >= 224:
                return True
        except (ValueError, IndexError):
            return False
        return False

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection to show route details."""
        if event.row_key is None:
            return

        # Get the selected row data
        table = self.query_one("#rib-file-table", DataTable)

        # Get the original route by matching the prefix
        selected_route = None
        for route in self.all_routes:
            if route.prefix == event.row_key.value:
                selected_route = route
                break

        if selected_route is None:
            return

        # Create route dictionary for the detail screen
        route_dict = {
            "prefix": selected_route.prefix,
            "table": selected_route.table,
            "protocol": selected_route.protocol,
            "next_hop": selected_route.next_hop,
            "age": selected_route.age,
            "active": selected_route.active,
            "attributes": {"protocol": selected_route.protocol},
        }

        # Extract protocol-specific attributes
        if selected_route.protocol.upper() == "BGP":
            route_dict["attributes"].update(
                {
                    "as_path": selected_route.as_path or "N/A",
                    "local_pref": selected_route.local_pref or "N/A",
                    "med": selected_route.med or "N/A",
                    "communities": getattr(selected_route, "communities", []),
                }
            )

        # Show detail screen
        self.app.push_screen(
            RouteDetailScreen(route_dict), callback=self._return_to_rib_screen
        )
