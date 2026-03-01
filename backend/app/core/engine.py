import time
import uuid
from typing import List, Dict, Optional
from shared.schemas import RouteEntry, Anomaly, AnomalyType, ProtocolType, BGPAttributes, OSPFAttributes

class DifferenceEngine:
    """
    Core logic to compare router states and identify anomalies.
    """
    
    def __init__(self):
        # We might want to persist state in Redis, but for the engine logic, 
        # we'll accept previous and current states as arguments.
        pass

    def detect_anomalies(
        self, 
        previous_state: Dict[str, RouteEntry], 
        current_state: Dict[str, RouteEntry]
    ) -> List[Anomaly]:
        anomalies = []
        
        # Check for changed or new routes
        for key, current_route in current_state.items():
            prev_route = previous_state.get(key)
            
            if prev_route:
                # 1. Administrative Distance Flip
                # (Assuming protocol change implies distance change in Juniper logic)
                if prev_route.protocol != current_route.protocol:
                    anomalies.append(self._create_anomaly(
                        anomaly_type=AnomalyType.ADMIN_DISTANCE_FLIP,
                        severity="Critical",
                        prefix=current_route.prefix,
                        message=f"Protocol changed from {prev_route.protocol} to {current_route.protocol}",
                        details={
                            "old_protocol": prev_route.protocol,
                            "new_protocol": current_route.protocol,
                            "old_next_hop": prev_route.next_hop,
                            "new_next_hop": current_route.next_hop
                        }
                    ))

                # 2. Metric Instability
                self._check_metric_instability(prev_route, current_route, anomalies)
                
                # 3. Next-hop changes
                if prev_route.next_hop != current_route.next_hop:
                    # This could be a normal convergence or an anomaly if recursive lookup fails
                    # Simplified for now: Log as info/warning if it changes frequently
                    pass
            else:
                # New route appearing - usually not an anomaly unless it's a hijack
                # Path Hijack logic would need a whitelist or historical analysis
                pass

        return anomalies

    def _check_metric_instability(self, prev: RouteEntry, current: RouteEntry, anomalies: List[Anomaly]):
        """
        Detect significant or frequent changes in metrics.
        """
        if prev.protocol == ProtocolType.BGP and current.protocol == ProtocolType.BGP:
            prev_attr: BGPAttributes = prev.attributes
            curr_attr: BGPAttributes = current.attributes
            if prev_attr.med != curr_attr.med:
                anomalies.append(self._create_anomaly(
                    anomaly_type=AnomalyType.METRIC_INSTABILITY,
                    severity="Warning",
                    prefix=current.prefix,
                    message=f"BGP MED changed from {prev_attr.med} to {curr_attr.med}",
                    details={"old_med": prev_attr.med, "new_med": curr_attr.med}
                ))

        elif prev.protocol == ProtocolType.OSPF and current.protocol == ProtocolType.OSPF:
            prev_attr: OSPFAttributes = prev.attributes
            curr_attr: OSPFAttributes = current.attributes
            if prev_attr.metric != curr_attr.metric:
                 anomalies.append(self._create_anomaly(
                    anomaly_type=AnomalyType.METRIC_INSTABILITY,
                    severity="Warning",
                    prefix=current.prefix,
                    message=f"OSPF Metric changed from {prev_attr.metric} to {curr_attr.metric}",
                    details={"old_metric": prev_attr.metric, "new_metric": curr_attr.metric}
                ))

    def _create_anomaly(
        self, 
        anomaly_type: AnomalyType, 
        severity: str, 
        prefix: str, 
        message: str, 
        details: dict
    ) -> Anomaly:
        return Anomaly(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            anomaly_type=anomaly_type,
            severity=severity,
            prefix=prefix,
            message=message,
            details=details
        )
