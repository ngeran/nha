"""
Anomaly Detection Engine - Detects network anomalies from routing table differences.

This module analyzes DiffResult objects to identify specific network events:
- Route failover events
- BGP path changes
- Convergence issues
- Device failures
- Traffic engineering changes
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from enum import Enum

from shared.diff_engine import DiffResult, SEVERITY_ORDER


class AnomalyType(Enum):
    ROUTE_FAILOVER = "Route Failover"
    BGP_PATH_CHANGE = "BGP Path Change"
    ORIGIN_AS_CHANGE = "Origin AS Change"
    PEER_FAILURE = "Peer Failure"
    TRAFFIC_ENGINEERING = "Traffic Engineering"
    PROTOCOL_SWITCH = "Protocol Switch"
    ROUTE_MISSING = "Route Missing"
    ROUTE_ADDED = "Route Added"
    CONVERGENCE_ISSUE = "Convergence Issue"
    NEXT_HOP_CHANGE = "Next-Hop Change"
    COMMUNITY_CHANGE = "Community Change"


class AnomalySeverity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class Anomaly:
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    table: str
    prefix: str
    description: str
    affected_devices: List[str]
    related_diffs: List[DiffResult] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_summary(self) -> str:
        sev_colors = {
            AnomalySeverity.CRITICAL: "#f7768e",
            AnomalySeverity.HIGH: "#ff9e64",
            AnomalySeverity.MEDIUM: "#e0af68",
            AnomalySeverity.LOW: "#7aa2f7",
        }
        color = sev_colors.get(self.severity, "#c0caf5")
        devices = ", ".join(self.affected_devices[:3])
        if len(self.affected_devices) > 3:
            devices += f" +{len(self.affected_devices) - 3}"
        return f"[{color}]{self.severity.value}[/] [{color}]{self.anomaly_type.value}[/] {self.prefix} ({devices})"


@dataclass
class AnomalyReport:
    anomalies: List[Anomaly] = field(default_factory=list)
    total_anomalies: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    critical_prefixes: List[str] = field(default_factory=list)

    def get_summary_text(self) -> str:
        if not self.anomalies:
            return "No anomalies detected"

        lines = [f"Detected {self.total_anomalies} anomalies:"]
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = self.by_severity.get(sev, 0)
            if count > 0:
                lines.append(f"  {sev}: {count}")

        return "\n".join(lines)


class AnomalyDetectionEngine:
    """
    Engine for detecting network anomalies from routing table differences.

    Analyzes DiffResult objects to identify specific network events
    like failovers, BGP changes, and convergence issues.
    """

    def __init__(self):
        self.anomalies: List[Anomaly] = []

    def analyze(self, diffs: List[DiffResult], devices: List[str]) -> AnomalyReport:
        """
        Analyze differences to detect anomalies.

        Args:
            diffs: List of DiffResult objects from comparison
            devices: List of device names being compared

        Returns:
            AnomalyReport with detected anomalies and statistics
        """
        self.anomalies = []

        grouped = self._group_diffs_by_route(diffs)

        for route_key, route_diffs in grouped.items():
            route_anomalies = self._detect_route_anomalies(
                route_key, route_diffs, devices
            )
            self.anomalies.extend(route_anomalies)

        self.anomalies.sort(
            key=lambda a: (
                SEVERITY_ORDER.get(a.severity.value, 99),
                a.table,
                a.prefix,
            )
        )

        return self._build_report()

    def _group_diffs_by_route(
        self, diffs: List[DiffResult]
    ) -> Dict[tuple, List[DiffResult]]:
        grouped: Dict[tuple, List[DiffResult]] = {}
        for diff in diffs:
            key = (diff.table, diff.prefix, diff.is_active)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(diff)
        return grouped

    def _detect_route_anomalies(
        self,
        route_key: tuple,
        diffs: List[DiffResult],
        devices: List[str],
    ) -> List[Anomaly]:
        anomalies = []
        table, prefix, is_active = route_key

        diff_map = {
            d.field.lower().replace("-", "_").replace(" ", "_"): d for d in diffs
        }

        presence_diff = diff_map.get("status")
        if presence_diff:
            missing_devices = [
                dev for dev, val in presence_diff.values.items() if val == "MISSING"
            ]
            present_devices = [
                dev for dev, val in presence_diff.values.items() if val == "PRESENT"
            ]

            if missing_devices:
                anomaly_type = (
                    AnomalyType.ROUTE_MISSING
                    if len(missing_devices) == 1
                    else AnomalyType.ROUTE_ADDED
                )
                anomalies.append(
                    Anomaly(
                        anomaly_type=anomaly_type,
                        severity=AnomalySeverity.CRITICAL,
                        table=table,
                        prefix=prefix,
                        description=f"Route {'missing on ' + ', '.join(missing_devices) if missing_devices else 'added'}",
                        affected_devices=missing_devices
                        if missing_devices
                        else present_devices,
                        related_diffs=[presence_diff],
                        metadata={"missing_on": ",".join(missing_devices)},
                    )
                )

        if len(diff_map) < 2:
            return anomalies

        gateway_diff = diff_map.get("gateway")
        if gateway_diff and self._has_difference(gateway_diff):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.NEXT_HOP_CHANGE,
                    severity=AnomalySeverity.CRITICAL,
                    table=table,
                    prefix=prefix,
                    description=f"Next-hop changed: {self._format_values(gateway_diff.values)}",
                    affected_devices=devices,
                    related_diffs=[gateway_diff],
                    metadata={"old_next_hop": "", "new_next_hop": ""},
                )
            )

        protocol_diff = diff_map.get("protocol")
        if protocol_diff and self._has_difference(protocol_diff):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.PROTOCOL_SWITCH,
                    severity=AnomalySeverity.CRITICAL,
                    table=table,
                    prefix=prefix,
                    description=f"Protocol changed: {self._format_values(protocol_diff.values)}",
                    affected_devices=devices,
                    related_diffs=[protocol_diff],
                )
            )

        origin_as_diff = diff_map.get("origin_as")
        if origin_as_diff and self._has_difference(origin_as_diff):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.ORIGIN_AS_CHANGE,
                    severity=AnomalySeverity.HIGH,
                    table=table,
                    prefix=prefix,
                    description=f"Origin AS changed: {self._format_values(origin_as_diff.values)}",
                    affected_devices=devices,
                    related_diffs=[origin_as_diff],
                )
            )

        as_path_diff = diff_map.get("as_path")
        if as_path_diff and self._has_difference(as_path_diff):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.BGP_PATH_CHANGE,
                    severity=AnomalySeverity.MEDIUM,
                    table=table,
                    prefix=prefix,
                    description=f"AS path changed: {self._format_values(as_path_diff.values)}",
                    affected_devices=devices,
                    related_diffs=[as_path_diff],
                )
            )

        learned_from_diff = diff_map.get("learned_from")
        if learned_from_diff and self._has_difference(learned_from_diff):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.PEER_FAILURE,
                    severity=AnomalySeverity.HIGH,
                    table=table,
                    prefix=prefix,
                    description=f"Learned-from changed: {self._format_values(learned_from_diff.values)}",
                    affected_devices=devices,
                    related_diffs=[learned_from_diff],
                )
            )

        local_pref_diff = diff_map.get("local_pref")
        med_diff = diff_map.get("med")

        if (local_pref_diff and self._has_difference(local_pref_diff)) or (
            med_diff and self._has_difference(med_diff)
        ):
            related = []
            if local_pref_diff:
                related.append(local_pref_diff)
            if med_diff:
                related.append(med_diff)
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.TRAFFIC_ENGINEERING,
                    severity=AnomalySeverity.MEDIUM,
                    table=table,
                    prefix=prefix,
                    description="Traffic engineering attributes changed",
                    affected_devices=devices,
                    related_diffs=related,
                )
            )

        community_diff = diff_map.get("communities")
        if community_diff and self._has_difference(community_diff):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.COMMUNITY_CHANGE,
                    severity=AnomalySeverity.LOW,
                    table=table,
                    prefix=prefix,
                    description=f"Communities changed: {self._format_values(community_diff.values)}",
                    affected_devices=devices,
                    related_diffs=[community_diff],
                )
            )

        if (
            gateway_diff
            and origin_as_diff
            and self._has_difference(gateway_diff)
            and self._has_difference(origin_as_diff)
        ):
            anomalies.append(
                Anomaly(
                    anomaly_type=AnomalyType.ROUTE_FAILOVER,
                    severity=AnomalySeverity.CRITICAL,
                    table=table,
                    prefix=prefix,
                    description="Route failover detected (next-hop + origin AS changed)",
                    affected_devices=devices,
                    related_diffs=[gateway_diff, origin_as_diff],
                )
            )

        return anomalies

    def _has_difference(self, diff: DiffResult) -> bool:
        values = list(diff.values.values())
        if not values:
            return False
        first = values[0]
        return not all(v == first for v in values[1:])

    def _format_values(self, values: Dict[str, str]) -> str:
        parts = []
        for dev, val in values.items():
            short_dev = dev[:15] + "..." if len(dev) > 15 else dev
            parts.append(f"{short_dev}={val}")
        return " | ".join(parts)

    def _build_report(self) -> AnomalyReport:
        report = AnomalyReport()
        report.anomalies = self.anomalies
        report.total_anomalies = len(self.anomalies)

        for anomaly in self.anomalies:
            type_name = anomaly.anomaly_type.value
            report.by_type[type_name] = report.by_type.get(type_name, 0) + 1

            sev_name = anomaly.severity.value
            report.by_severity[sev_name] = report.by_severity.get(sev_name, 0) + 1

            if anomaly.severity == AnomalySeverity.CRITICAL:
                report.critical_prefixes.append(anomaly.prefix)

        report.critical_prefixes = list(set(report.critical_prefixes))

        return report

    def get_anomalies_by_type(self, anomaly_type: AnomalyType) -> List[Anomaly]:
        return [a for a in self.anomalies if a.anomaly_type == anomaly_type]

    def get_anomalies_by_severity(self, severity: AnomalySeverity) -> List[Anomaly]:
        return [a for a in self.anomalies if a.severity == severity]

    def get_anomalies_by_prefix(self, prefix: str) -> List[Anomaly]:
        return [a for a in self.anomalies if a.prefix == prefix]
