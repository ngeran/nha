import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.schemas import RouteEntry, ProtocolType, BGPAttributes, OSPFAttributes, StaticAttributes
from backend.app.core.engine import DifferenceEngine

def test_admin_distance_flip():
    engine = DifferenceEngine()
    
    prefix = "192.168.1.0/24"
    
    prev_state = {
        f"{prefix}:inet.0:BGP": RouteEntry(
            prefix=prefix,
            table="inet.0",
            protocol=ProtocolType.BGP,
            next_hop="10.0.0.1",
            age=100,
            attributes=BGPAttributes(as_path="65001 65002", med=100)
        )
    }
    
    current_state = {
        f"{prefix}:inet.0:OSPF": RouteEntry(
            prefix=prefix,
            table="inet.0",
            protocol=ProtocolType.OSPF,
            next_hop="10.0.0.2",
            age=10,
            attributes=OSPFAttributes(area_id="0.0.0.0", metric=10)
        )
    }
    
    anomalies = engine.detect_anomalies(prev_state, current_state)
    
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "ADMIN_DISTANCE_FLIP"
    print("✅ Admin Distance Flip detection passed")

def test_metric_instability():
    engine = DifferenceEngine()
    
    prefix = "10.0.0.0/8"
    
    prev_state = {
        f"{prefix}:inet.0:BGP": RouteEntry(
            prefix=prefix,
            table="inet.0",
            protocol=ProtocolType.BGP,
            next_hop="1.1.1.1",
            age=1000,
            attributes=BGPAttributes(as_path="65000", med=100)
        )
    }
    
    current_state = {
        f"{prefix}:inet.0:BGP": RouteEntry(
            prefix=prefix,
            table="inet.0",
            protocol=ProtocolType.BGP,
            next_hop="1.1.1.1",
            age=10,
            attributes=BGPAttributes(as_path="65000", med=200)
        )
    }
    
    anomalies = engine.detect_anomalies(prev_state, current_state)
    
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "METRIC_INSTABILITY"
    print("✅ Metric Instability detection passed")

if __name__ == "__main__":
    try:
        test_admin_distance_flip()
        test_metric_instability()
        print("\nAll engine tests passed!")
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
