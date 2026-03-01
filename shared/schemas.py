from enum import Enum
from typing import List, Optional, Union, Literal
from pydantic import BaseModel, Field, ConfigDict

class ProtocolType(str, Enum):
    BGP = "BGP"
    OSPF = "OSPF"
    ISIS = "IS-IS"
    STATIC = "Static"
    LOCAL = "Local"
    DIRECT = "Direct"

class BaseRouteAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore")

class BGPAttributes(BaseRouteAttributes):
    protocol: Literal[ProtocolType.BGP] = ProtocolType.BGP
    as_path: str
    local_pref: Optional[int] = None
    med: Optional[int] = None
    communities: List[str] = Field(default_factory=list)

class OSPFAttributes(BaseRouteAttributes):
    protocol: Literal[ProtocolType.OSPF] = ProtocolType.OSPF
    area_id: str
    metric: int
    metric2: Optional[int] = None

class StaticAttributes(BaseRouteAttributes):
    protocol: Literal[ProtocolType.STATIC] = ProtocolType.STATIC
    preference: int

class LocalAttributes(BaseRouteAttributes):
    protocol: Literal[ProtocolType.LOCAL] = ProtocolType.LOCAL

class DirectAttributes(BaseRouteAttributes):
    protocol: Literal[ProtocolType.DIRECT] = ProtocolType.DIRECT

# Discriminated Union for attributes
RouteAttributes = Union[
    BGPAttributes,
    OSPFAttributes,
    StaticAttributes,
    LocalAttributes,
    DirectAttributes
]

class RouteEntry(BaseModel):
    prefix: str
    table: str = "inet.0"
    protocol: ProtocolType
    next_hop: str
    age: int  # in seconds
    attributes: RouteAttributes = Field(..., discriminator="protocol")

class AnomalyType(str, Enum):
    ADMIN_DISTANCE_FLIP = "ADMIN_DISTANCE_FLIP"
    METRIC_INSTABILITY = "METRIC_INSTABILITY"
    NEXT_HOP_RECURSION_FAILURE = "NEXT_HOP_RECURSION_FAILURE"
    PATH_HIJACK = "PATH_HIJACK"

class Anomaly(BaseModel):
    id: str
    timestamp: float
    anomaly_type: AnomalyType
    severity: str  # Critical, Warning, Info
    prefix: str
    message: str
    details: dict

class RouteEvent(BaseModel):
    event_type: str  # ADD, UPDATE, DELETE
    timestamp: float
    route: RouteEntry

class ConnectionConfig(BaseModel):
    host: str
    user: str
    password: str
    port: int = 830
    mode: str = "ssh" # ssh, telnet, serial
