"""
analysis_engine.py
==================
Analyses a single BGP routing table (RIB) and produces a structured
:class:`AnalysisReport` covering:

* Basic route counts  (total / active / BGP)
* AS-path statistics  (unique paths, average / min / max length)
* Origin-AS grouping  (which ASes originate the most prefixes)
* Self-originated route detection (routes with no external AS path)
* Non-default BGP attribute detection (Local-Pref ≠ 100, MED ≠ 0, communities)

Typical usage
-------------
    from analysis_engine import AnalysisEngine

    engine = AnalysisEngine()
    report = engine.analyze(routes)          # routes: List[RouteInfo]
    print(engine.get_summary_text(report))

Thread safety
-------------
:meth:`AnalysisEngine.analyze` keeps all state in a local ``report`` variable
and does not mutate ``self``, so multiple threads may call it concurrently on
the same engine instance without synchronisation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from shared.rib_reader import RouteInfo


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# BGP origin-code tokens and the special "Aggregated" marker that can appear
# as standalone whitespace-separated tokens inside an AS-path string.
# These are *not* real ASNs and must be ignored when counting path length or
# deriving the origin AS.
#
# Standard BGP origin codes (RFC 4271 §4.3):
#   I  – IGP (network was locally injected)
#   E  – EGP (legacy, rarely seen)
#   ?  – Incomplete (redistributed from another protocol)
_ORIGIN_CODE_TOKENS: frozenset[str] = frozenset({"I", "E", "?", "Aggregated"})

# Maximum number of prefixes stored inside each :class:`OriginASGroup`.
# This caps per-group memory consumption for ASes that originate thousands of
# prefixes (e.g. large CDNs or tier-1 carriers).  The *count* field always
# reflects the true total; only the stored list is truncated.
_MAX_PREFIXES_PER_GROUP: int = 100


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _as_path_tokens(as_path: str) -> List[str]:
    """
    Split *as_path* on whitespace and return only the real ASN tokens.

    Origin-code markers (``I``, ``E``, ``?``) and the ``Aggregated`` keyword
    are stripped because they are not autonomous system numbers.

    Examples::

        _as_path_tokens("65001 65002 I")   -> ["65001", "65002"]
        _as_path_tokens("I")               -> []
        _as_path_tokens("")                -> []
        _as_path_tokens("65001 ?")         -> ["65001"]

    Args:
        as_path: Raw AS-path string as stored in :class:`~shared.rib_reader.RouteInfo`.

    Returns:
        Ordered list of ASN strings with non-ASN tokens removed.
    """
    return [token for token in as_path.split() if token not in _ORIGIN_CODE_TOKENS]


def _is_self_originated(as_path: str) -> bool:
    """
    Return ``True`` when *as_path* contains no external ASNs.

    A route is considered self-originated when the router injected it into BGP
    itself (via ``network`` statement, redistribution, or aggregation) rather
    than receiving it from a peer.  Such routes have an empty AS path, or one
    that contains only origin-code tokens with no real ASNs.

    Examples::

        _is_self_originated("")            -> True   # no path at all
        _is_self_originated("I")           -> True   # only origin code
        _is_self_originated("?")           -> True   # incomplete origin, still local
        _is_self_originated("65001 I")     -> False  # real ASN present
        _is_self_originated("65001 65002") -> False

    Args:
        as_path: Stripped AS-path string.

    Returns:
        ``True`` if the route was locally originated, ``False`` otherwise.
    """
    return len(_as_path_tokens(as_path)) == 0


def _store_prefixes(prefixes: List[str]) -> Tuple[List[str], bool]:
    """
    Truncate *prefixes* to :data:`_MAX_PREFIXES_PER_GROUP` entries.

    Args:
        prefixes: Full list of prefix strings for a group.

    Returns:
        A ``(stored, truncated)`` tuple where *stored* is the (possibly
        shortened) list and *truncated* is ``True`` when entries were dropped.
    """
    if len(prefixes) > _MAX_PREFIXES_PER_GROUP:
        return prefixes[:_MAX_PREFIXES_PER_GROUP], True
    return prefixes, False


def ip_to_int(ip_str: str) -> int:
    """
    Convert an IPv4 address string to an integer for range comparisons.

    Args:
        ip_str: IPv4 address in dotted decimal notation (e.g., "192.168.1.1")

    Returns:
        Integer representation of the IP address.

    Raises:
        ValueError: If the IP address format is invalid.
    """
    parts = ip_str.strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"Invalid IPv4 address: {ip_str}")

    result = 0
    for part in parts:
        octet = int(part)
        if not 0 <= octet <= 255:
            raise ValueError(f"Invalid octet in IP address: {ip_str}")
        result = (result << 8) | octet

    return result


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ASPathStats:
    """
    Aggregate statistics computed across all BGP AS paths in the RIB.

    Attributes:
        unique_paths:    Number of distinct AS-path strings.
        unique_origins:  Number of distinct origin ASes (last real ASN).
        avg_path_length: Mean number of ASNs per path (origin codes excluded).
        max_path_length: Longest path in ASN hops.
        min_path_length: Shortest path in ASN hops (0 for self-originated).
    """

    unique_paths: int = 0
    unique_origins: int = 0
    avg_path_length: float = 0.0
    max_path_length: int = 0
    min_path_length: int = 0


@dataclass
class OriginASGroup:
    """
    A collection of prefixes that share the same origin AS.

    Attributes:
        origin_as:          The originating AS number as a string, or ``"Local"``
                            for self-originated routes.
        count:              True total number of prefixes for this AS (not
                            limited by :data:`_MAX_PREFIXES_PER_GROUP`).
        prefixes:           Up to :data:`_MAX_PREFIXES_PER_GROUP` example
                            prefixes for display / drill-down purposes.
        is_self_originated: ``True`` when this group represents routes injected
                            by the local router (no external AS path).
        prefixes_truncated: ``True`` when *count* exceeds
                            :data:`_MAX_PREFIXES_PER_GROUP` and the *prefixes*
                            list was therefore cut short.
    """

    origin_as: str
    count: int
    prefixes: List[str] = field(default_factory=list)
    is_self_originated: bool = False
    prefixes_truncated: bool = False


@dataclass
class TransitASGroup:
    """
    A transit AS that appears in the middle of AS paths.

    Transit ASes carry traffic between origin and destination, appearing
    in the middle of AS paths rather than as the origin.

    Attributes:
        transit_as:   The AS number acting as transit.
        count:        Number of routes whose path includes this transit AS.
        prefixes:     Sample prefixes using this transit AS.
        as_origins:   Set of origin ASes that use this transit AS.
    """

    transit_as: str
    count: int
    prefixes: List[str] = field(default_factory=list)
    as_origins: Set[str] = field(default_factory=set)


@dataclass
class PeerGroup:
    """
    Routes learned from a specific BGP peer/neighbor.

    Attributes:
        peer_address:   The IP address of the BGP neighbor.
        peer_as:        The AS number of the peer (if available).
        count:          Number of routes learned from this peer.
        prefixes:       Sample prefixes learned from this peer.
        active_count:   Number of active (best-path) routes from this peer.
        protocols:      Set of protocols advertised by this peer.
    """

    peer_address: str
    peer_as: str = ""
    count: int = 0
    prefixes: List[str] = field(default_factory=list)
    active_count: int = 0
    protocols: Set[str] = field(default_factory=set)


@dataclass
class ProtocolBreakdown:
    """
    Route count breakdown by routing protocol.

    Attributes:
        protocol:   Protocol name (BGP, OSPF, IS-IS, Static, Connected, etc.).
        count:      Total routes from this protocol.
        active:     Active routes from this protocol.
        tables:     Set of routing tables where this protocol appears.
    """

    protocol: str
    count: int = 0
    active: int = 0
    tables: Set[str] = field(default_factory=set)


@dataclass
class ASPrependingRoute:
    """
    A route with AS path prepending detected.

    AS prepending occurs when the same AS appears multiple times consecutively
    in the AS path, typically used for traffic engineering to make a path
    less desirable.

    Attributes:
        prefix:         The IP prefix with prepending detected.
        as_path:        The full AS path string.
        prepended_as:   The AS number that was prepended.
        repeat_count:   How many times the AS appears consecutively.
        route:          The full RouteInfo object.
    """

    prefix: str
    as_path: str
    prepended_as: str
    repeat_count: int
    route: RouteInfo


@dataclass
class RouteAgeStats:
    """
    Statistics about route ages in the RIB.

    Route age indicates how long a route has been known, which helps
    identify stable vs. unstable routes.

    Attributes:
        oldest_age:         Maximum age (seconds) of any route.
        newest_age:         Minimum age (seconds) of any route (usually 0).
        avg_age:            Average age across all routes.
        median_age:         Median age value.
        routes_under_1min:  Routes learned in last 60 seconds.
        routes_under_1hr:   Routes learned in last hour.
        routes_under_1day:  Routes learned in last 24 hours.
        routes_over_1day:   Routes older than 24 hours.
    """

    oldest_age: int = 0
    newest_age: int = 0
    avg_age: float = 0.0
    median_age: int = 0
    routes_under_1min: int = 0
    routes_under_1hr: int = 0
    routes_under_1day: int = 0
    routes_over_1day: int = 0


@dataclass
class PrefixLengthGroup:
    """
    A group of routes with the same prefix length.

    Attributes:
        prefix_len:     The prefix length (e.g., 24 for /24).
        count:          Number of routes with this prefix length.
        percentage:     Percentage of total routes.
        prefixes:       Sample prefixes with this length.
        is_specific:    True if prefix is very specific (/28-/32 for IPv4).
        is_aggregate:   True if prefix is an aggregate (/8-/16 for IPv4).
    """

    prefix_len: int
    count: int
    percentage: float = 0.0
    prefixes: List[str] = field(default_factory=list)
    is_specific: bool = False
    is_aggregate: bool = False


@dataclass
class PrefixCoverage:
    """
    Analysis of special prefix coverage in the RIB.

    Identifies routes that match special address ranges:
    * Default routes (0.0.0.0/0, ::/0)
    * RFC1918 private addresses (10/8, 172.16/12, 192.168/16)
    * Link-local (169.254/16, fe80::/10)
    * Loopback (127/8, ::1/128)
    * Documentation (192.0.2/24, 198.51.100/24, 203.0.113/24)
    * Bogons (unallocated/martian addresses)

    Attributes:
        has_default_ipv4:       Has IPv4 default route.
        has_default_ipv6:       Has IPv6 default route.
        rfc1918_routes:         List of RFC1918 private routes.
        rfc1918_count:          Count of RFC1918 routes.
        link_local_routes:      List of link-local routes.
        link_local_count:       Count of link-local routes.
        loopback_routes:        List of loopback routes.
        loopback_count:         Count of loopback routes.
        bogon_routes:           List of bogon/martian routes.
        bogon_count:            Count of bogon routes.
    """

    has_default_ipv4: bool = False
    has_default_ipv6: bool = False
    rfc1918_routes: List[str] = field(default_factory=list)
    rfc1918_count: int = 0
    link_local_routes: List[str] = field(default_factory=list)
    link_local_count: int = 0
    loopback_routes: List[str] = field(default_factory=list)
    loopback_count: int = 0
    bogon_routes: List[str] = field(default_factory=list)
    bogon_count: int = 0


@dataclass
class BGPAttributeAnomaly:
    """
    A single BGP route whose attributes deviate from the expected defaults.

    Attributes:
        prefix:        The IP prefix (CIDR notation) of the affected route.
        attribute:     Human-readable attribute name, e.g. ``"Local-Pref"``.
        value:         The actual attribute value observed on the route.
        default_value: The baseline value the attribute is expected to hold.
        route:         The full :class:`~shared.rib_reader.RouteInfo` record
                       for further inspection.
    """

    prefix: str
    attribute: str
    value: str
    default_value: str
    route: RouteInfo


@dataclass
class AnalysisReport:
    """
    Complete analysis output produced by :class:`AnalysisEngine`.

    Sections
    --------
    **Basic counts**
        ``total_routes``, ``active_routes``, ``bgp_routes``

    **AS-path statistics**
        ``as_path_stats`` – see :class:`ASPathStats`

    **Origin grouping**
        ``origin_groups``   – list of :class:`OriginASGroup`, sorted by count
                              descending.
        ``self_originated``  – a special group for routes with no external path.
        ``top_origins``      – shortlist of the 10 largest origin ASes.
        ``top_as_paths``     – the 5 most-seen complete AS-path strings.

    **BGP attribute anomalies**
        ``non_default_lp``   – routes whose Local-Pref ≠ 100.
        ``non_default_med``  – routes whose MED ≠ 0.
        ``with_communities`` – routes that carry at least one BGP community.
    """

    # --- Basic counts -------------------------------------------------------

    total_routes: int = 0
    """Total number of routes in the RIB regardless of protocol or state."""

    active_routes: int = 0
    """Routes currently selected as best-path (``RouteInfo.active == True``)."""

    bgp_routes: int = 0
    """Routes whose protocol field is ``"BGP"`` (case-insensitive)."""

    # --- AS-path statistics -------------------------------------------------

    as_path_stats: ASPathStats = field(default_factory=ASPathStats)
    """Aggregated path-length and uniqueness metrics for all BGP routes."""

    # --- Origin grouping ----------------------------------------------------

    origin_groups: List[OriginASGroup] = field(default_factory=list)
    """All external origin AS groups, sorted by prefix count descending."""

    self_originated: OriginASGroup = field(default_factory=lambda: OriginASGroup("", 0))
    """Routes locally originated by this router (empty / marker-only AS path)."""

    # --- Transit AS analysis -------------------------------------------------

    transit_as_groups: List[TransitASGroup] = field(default_factory=list)
    """Transit ASes appearing in middle of paths, sorted by count descending."""

    top_transit: List[Tuple[str, int]] = field(default_factory=list)
    """Top-10 ``(transit_as, count)`` pairs showing most-used transit ASes."""

    # --- Peer/Neighbor analysis ----------------------------------------------

    peer_groups: List[PeerGroup] = field(default_factory=list)
    """Routes grouped by BGP peer/neighbor (learned_from field)."""

    top_peers: List[Tuple[str, int]] = field(default_factory=list)
    """Top-5 ``(peer_address, count)`` pairs showing largest peers."""

    # --- Protocol breakdown --------------------------------------------------

    protocol_breakdown: List[ProtocolBreakdown] = field(default_factory=list)
    """Route counts by protocol (BGP, OSPF, Static, etc.)."""

    protocol_summary: Dict[str, int] = field(default_factory=dict)
    """Quick lookup: protocol name -> route count."""

    # --- AS Path prepending --------------------------------------------------

    prepending_routes: List[ASPrependingRoute] = field(default_factory=list)
    """Routes with AS path prepending (same AS repeated consecutively)."""

    prepending_count: int = 0
    """Total number of routes with prepending detected."""

    prepending_by_as: Dict[str, int] = field(default_factory=dict)
    """Count of prepended routes by the AS doing the prepending."""

    # --- Route Age Analysis --------------------------------------------------

    route_age_stats: RouteAgeStats = field(default_factory=RouteAgeStats)
    """Statistics about route ages in the RIB."""

    newest_routes: List[Tuple[str, int]] = field(default_factory=list)
    """Top-5 newest routes as ``(prefix, age_seconds)`` pairs."""

    oldest_routes: List[Tuple[str, int]] = field(default_factory=list)
    """Top-5 oldest routes as ``(prefix, age_seconds)`` pairs."""

    # --- Prefix Length Distribution -----------------------------------------

    prefix_length_groups: List[PrefixLengthGroup] = field(default_factory=list)
    """Routes grouped by prefix length, sorted by count descending."""

    prefix_length_summary: Dict[int, int] = field(default_factory=dict)
    """Quick lookup: prefix_len -> count."""

    specific_routes_count: int = 0
    """Routes with very specific prefixes (/28-/32 for IPv4, /124-/128 for IPv6)."""

    aggregate_routes_count: int = 0
    """Routes with aggregate prefixes (/8-/16 for IPv4, /32-/48 for IPv6)."""

    # --- Prefix Coverage -----------------------------------------------------

    prefix_coverage: PrefixCoverage = field(default_factory=PrefixCoverage)
    """Analysis of special prefix coverage (default, RFC1918, bogons)."""

    # --- Top-N shortcuts ----------------------------------------------------

    top_origins: List[Tuple[str, int]] = field(default_factory=list)
    """Top-10 ``(origin_as, count)`` pairs from ``origin_groups``."""

    top_as_paths: List[Tuple[str, int]] = field(default_factory=list)
    """Top-5 ``(as_path_string, count)`` pairs by frequency."""

    # --- BGP attribute anomalies --------------------------------------------

    non_default_lp: List[BGPAttributeAnomaly] = field(default_factory=list)
    """Routes with Local-Pref != :attr:`AnalysisEngine.DEFAULT_LOCAL_PREF`."""

    non_default_med: List[BGPAttributeAnomaly] = field(default_factory=list)
    """Routes with MED != :attr:`AnalysisEngine.DEFAULT_MED`."""

    with_communities: List[BGPAttributeAnomaly] = field(default_factory=list)
    """Routes that carry one or more BGP communities."""

    # --- UI helper ----------------------------------------------------------

    def get_summary_chips(self) -> Dict[str, Tuple[str, int, str]]:
        """
        Return a mapping of short metric chips for dashboard display.

        Each value is a ``(label, count, severity)`` tuple where *severity* is
        one of ``""`` (neutral), ``"info"``, ``"warning"``, or ``"critical"``.

        Returns:
            Dict keyed by a stable identifier string.
        """
        return {
            "total": ("Total", self.total_routes, ""),
            "active": ("Active", self.active_routes, ""),
            "bgp": ("BGP", self.bgp_routes, "info"),
            "origins": ("Origins", self.as_path_stats.unique_origins, "info"),
            "self_orig": ("Self-Originated", self.self_originated.count, "warning"),
            "non_def_lp": ("Non-Def LP", len(self.non_default_lp), "critical"),
            "non_def_med": ("Non-Def MED", len(self.non_default_med), "warning"),
            "communities": ("Communities", len(self.with_communities), "info"),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class AnalysisEngine:
    """
    Stateless engine that analyses a list of :class:`~shared.rib_reader.RouteInfo`
    objects and returns an :class:`AnalysisReport`.

    Design notes
    ------------
    * All private ``_analyze_*`` methods receive both *routes* and *report* as
      explicit arguments so that no mutable state is stored on ``self``.
      This makes concurrent calls safe without locking.
    * ``get_routes_by_origin`` and ``get_summary_text`` are ``@staticmethod``s
      that operate on an already-computed report, keeping the engine itself
      free of long-lived state.
    * BGP attribute comparisons are done via ``int()`` conversion so that
      string representations (``"100"``) and integer values (``100``) are
      treated identically.  Unparseable values are silently skipped.
    """

    # Default BGP attribute values per RFC 4271 / common operational practice.

    DEFAULT_LOCAL_PREF: int = 100
    """Standard default Local Preference (RFC 4271 §5.1.5)."""

    DEFAULT_MED: int = 0
    """Standard default Multi-Exit Discriminator (RFC 4271 §5.1.4)."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, routes: List[RouteInfo]) -> AnalysisReport:
        """
        Analyse *routes* and return a populated :class:`AnalysisReport`.

        The analysis is broken into independent passes (basic stats,
        AS-path statistics, origin grouping, transit AS analysis, BGP attribute
        anomalies) so that each concern is isolated and easy to extend.

        Args:
            routes: Full list of :class:`~shared.rib_reader.RouteInfo` objects
                    representing the current RIB snapshot.

        Returns:
            A fully populated :class:`AnalysisReport`.
        """
        report = AnalysisReport()

        self._analyze_basic_stats(routes, report)
        self._analyze_as_paths(routes, report)
        self._analyze_origins(routes, report)
        self._analyze_transit_as(routes, report)
        self._analyze_peers(routes, report)
        self._analyze_protocols(routes, report)
        self._analyze_prepending(routes, report)
        self._analyze_route_age(routes, report)
        self._analyze_prefix_length(routes, report)
        self._analyze_prefix_coverage(routes, report)
        self._analyze_bgp_attributes(routes, report)

        return report

    # ------------------------------------------------------------------
    # Private analysis passes
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_basic_stats(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Populate the three top-level counters on *report*.

        Pass 1 of 4 – O(n) single scan.

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        report.total_routes = len(routes)

        # Count active (best-path selected) routes.
        report.active_routes = sum(1 for r in routes if r.active)

        # Count BGP routes; protocol field is compared case-insensitively so
        # values like "bgp", "BGP", and "Bgp" all match.
        report.bgp_routes = sum(1 for r in routes if r.protocol.upper() == "BGP")

    @staticmethod
    def _analyze_as_paths(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Compute AS-path statistics and populate ``report.as_path_stats``.

        Pass 2 of 4.

        Only routes whose protocol is ``"BGP"`` *and* that have a non-empty
        ``as_path`` field are included.  Self-originated routes (empty path)
        are counted with a path length of 0, which pulls down the average and
        sets min_path_length accordingly.

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        # Filter to BGP routes that have a path string at all.
        bgp_routes = [r for r in routes if r.protocol.upper() == "BGP" and r.as_path]

        if not bgp_routes:
            # Nothing to compute; leave ASPathStats at their zero defaults.
            return

        unique_paths: Set[str] = set()
        unique_origins: Set[str] = set()
        path_lengths: List[int] = []

        for route in bgp_routes:
            as_path = route.as_path.strip()

            # Accumulate the set of distinct path strings for uniqueness count.
            unique_paths.add(as_path)

            # Use the pre-parsed origin_as field when available (faster and
            # already validated by the RIB reader).
            if route.origin_as:
                unique_origins.add(route.origin_as)

            # Compute path length as the number of real ASNs; origin-code
            # tokens are excluded via _as_path_tokens.
            path_lengths.append(len(_as_path_tokens(as_path)))

        report.as_path_stats.unique_paths = len(unique_paths)
        report.as_path_stats.unique_origins = len(unique_origins)

        if path_lengths:
            report.as_path_stats.avg_path_length = sum(path_lengths) / len(path_lengths)
            report.as_path_stats.max_path_length = max(path_lengths)
            report.as_path_stats.min_path_length = min(path_lengths)

        # Build a frequency table of complete AS-path strings and keep top 5.
        path_counter: Counter[str] = Counter(r.as_path for r in bgp_routes)
        report.top_as_paths = path_counter.most_common(5)

    @staticmethod
    def _analyze_origins(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Group BGP prefixes by origin AS and populate ``report.origin_groups``.

        Pass 3 of 4.

        Self-originated routes are separated into ``report.self_originated``
        rather than appearing in the main ``origin_groups`` list.

        For routes that have an AS path but whose ``origin_as`` field is empty,
        the last real ASN token in the path is used as a fallback so no routes
        are silently discarded.

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        bgp_routes = [r for r in routes if r.protocol.upper() == "BGP"]

        # Accumulate prefix lists keyed by origin AS string.
        origin_map: Dict[str, List[str]] = {}

        # Separate bucket for routes this router originated itself.
        self_originated_prefixes: List[str] = []

        for route in bgp_routes:
            as_path = (route.as_path or "").strip()

            if _is_self_originated(as_path):
                # No external AS hops → route was locally injected.
                self_originated_prefixes.append(route.prefix)
                continue

            # Prefer the pre-parsed origin_as field; fall back to extracting
            # the last token of the AS path so routes are never silently dropped
            # when origin_as is absent.
            origin_as: Optional[str] = route.origin_as
            if not origin_as:
                tokens = _as_path_tokens(as_path)
                origin_as = tokens[-1] if tokens else None

            if origin_as:
                origin_map.setdefault(origin_as, []).append(route.prefix)
            # If origin_as is still None the route has a malformed path;
            # we skip it rather than crashing or misclassifying it.

        # Convert the accumulated map into a sorted list of OriginASGroup objects.
        for origin_as, prefixes in origin_map.items():
            stored, truncated = _store_prefixes(prefixes)
            report.origin_groups.append(
                OriginASGroup(
                    origin_as=origin_as,
                    count=len(prefixes),  # always the true total, never truncated
                    prefixes=stored,  # may be truncated to _MAX_PREFIXES_PER_GROUP
                    is_self_originated=False,
                    prefixes_truncated=truncated,
                )
            )

        # Sort descending by prefix count so the most prolific ASes appear first.
        report.origin_groups.sort(key=lambda g: g.count, reverse=True)

        # Convenience shortlist for dashboards and summary views.
        report.top_origins = [(g.origin_as, g.count) for g in report.origin_groups[:10]]

        # Populate the self-originated group only when such routes were found.
        if self_originated_prefixes:
            stored, truncated = _store_prefixes(self_originated_prefixes)
            report.self_originated = OriginASGroup(
                origin_as="Local",
                count=len(self_originated_prefixes),
                prefixes=stored,
                is_self_originated=True,
                prefixes_truncated=truncated,
            )

    @staticmethod
    def _analyze_transit_as(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Identify transit ASes that appear in the middle of AS paths.

        A transit AS is one that carries traffic between origin and destination,
        appearing in the middle of the AS path rather than as the origin (last AS).

        This analysis helps identify:
        * Which providers carry the most traffic
        * Unexpected transit paths (potential hijacks or misconfigurations)
        * Upstream provider diversity

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        bgp_routes = [r for r in routes if r.protocol.upper() == "BGP"]

        # Map: transit_as -> {"prefixes": [...], "origins": set(...)}
        transit_map: Dict[str, Dict] = {}

        for route in bgp_routes:
            as_path = (route.as_path or "").strip()
            tokens = _as_path_tokens(as_path)

            # Need at least 2 ASNs to have a transit (1 origin + 1+ transit)
            if len(tokens) < 2:
                continue

            # Origin is the last ASN, transit ASes are all except the last
            origin_as = tokens[-1]
            transit_ases = tokens[:-1]

            # Get the primary transit AS (first in path = closest to us)
            primary_transit = transit_ases[0] if transit_ases else None

            for transit_as in transit_ases:
                if transit_as not in transit_map:
                    transit_map[transit_as] = {"prefixes": [], "origins": set()}

                # Store prefix (limit to avoid memory bloat)
                if len(transit_map[transit_as]["prefixes"]) < _MAX_PREFIXES_PER_GROUP:
                    transit_map[transit_as]["prefixes"].append(route.prefix)

                # Track which origins use this transit
                transit_map[transit_as]["origins"].add(origin_as)

        # Convert to TransitASGroup objects and sort by count
        for transit_as, data in transit_map.items():
            report.transit_as_groups.append(
                TransitASGroup(
                    transit_as=transit_as,
                    count=len(data["prefixes"]),
                    prefixes=data["prefixes"],
                    as_origins=data["origins"],
                )
            )

        report.transit_as_groups.sort(key=lambda g: g.count, reverse=True)
        report.top_transit = [
            (g.transit_as, g.count) for g in report.transit_as_groups[:10]
        ]

    @staticmethod
    def _analyze_peers(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Group BGP routes by the peer/neighbor they were learned from.

        This analysis uses the ``learned_from`` field to identify which
        BGP neighbor advertised each route. This helps identify:
        * Which peers contribute the most routes
        * Peer route diversity and redundancy
        * Potential peer failures (missing routes from expected peer)

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        bgp_routes = [r for r in routes if r.protocol.upper() == "BGP"]

        # Map: peer_address -> {"prefixes": [...], "active": count, "protocols": set}
        peer_map: Dict[str, Dict] = {}

        for route in bgp_routes:
            peer = (route.learned_from or "").strip()
            if not peer:
                peer = "Unknown"

            if peer not in peer_map:
                peer_map[peer] = {"prefixes": [], "active": 0, "protocols": set()}

            if len(peer_map[peer]["prefixes"]) < _MAX_PREFIXES_PER_GROUP:
                peer_map[peer]["prefixes"].append(route.prefix)

            if route.active:
                peer_map[peer]["active"] += 1

            peer_map[peer]["protocols"].add(route.protocol)

        for peer_address, data in peer_map.items():
            report.peer_groups.append(
                PeerGroup(
                    peer_address=peer_address,
                    count=len(data["prefixes"]),
                    prefixes=data["prefixes"],
                    active_count=data["active"],
                    protocols=data["protocols"],
                )
            )

        report.peer_groups.sort(key=lambda g: g.count, reverse=True)
        report.top_peers = [(g.peer_address, g.count) for g in report.peer_groups[:5]]

    @staticmethod
    def _analyze_protocols(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Break down route counts by routing protocol.

        Groups routes by their ``protocol`` field to show distribution
        across BGP, OSPF, IS-IS, Static, Connected, etc.

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        # Map: protocol -> {"count": int, "active": int, "tables": set}
        protocol_map: Dict[str, Dict] = {}

        for route in routes:
            protocol = (route.protocol or "Unknown").strip()
            if not protocol:
                protocol = "Unknown"

            if protocol not in protocol_map:
                protocol_map[protocol] = {"count": 0, "active": 0, "tables": set()}

            protocol_map[protocol]["count"] += 1
            if route.active:
                protocol_map[protocol]["active"] += 1
            if route.table:
                protocol_map[protocol]["tables"].add(route.table)

        for protocol, data in protocol_map.items():
            report.protocol_breakdown.append(
                ProtocolBreakdown(
                    protocol=protocol,
                    count=data["count"],
                    active=data["active"],
                    tables=data["tables"],
                )
            )

        report.protocol_breakdown.sort(key=lambda p: p.count, reverse=True)
        report.protocol_summary = {
            p.protocol: p.count for p in report.protocol_breakdown
        }

    @staticmethod
    def _analyze_prepending(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Detect AS path prepending in BGP routes.

        AS prepending occurs when the same AS number appears multiple times
        consecutively in an AS path. This is typically done for traffic
        engineering to make a path less desirable (longer path = lower priority).

        This analysis identifies:
        * Routes with prepended AS paths
        * Which ASes are doing the prepending
        * How many times each AS is repeated

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        bgp_routes = [r for r in routes if r.protocol.upper() == "BGP"]

        prepending_by_as: Dict[str, int] = {}

        for route in bgp_routes:
            as_path = (route.as_path or "").strip()
            tokens = _as_path_tokens(as_path)

            if len(tokens) < 2:
                continue

            # Check for consecutive duplicate ASNs
            prev_asn = None
            repeat_count = 1
            prepended_as = None

            for token in tokens:
                if token == prev_asn:
                    repeat_count += 1
                    if repeat_count >= 2 and prepended_as is None:
                        prepended_as = token
                else:
                    if repeat_count >= 2:
                        break
                    repeat_count = 1
                prev_asn = token

            # If we found prepending (same AS appears 2+ times consecutively)
            if prepended_as and repeat_count >= 2:
                report.prepending_routes.append(
                    ASPrependingRoute(
                        prefix=route.prefix,
                        as_path=as_path,
                        prepended_as=prepended_as,
                        repeat_count=repeat_count,
                        route=route,
                    )
                )

                # Track which ASes are prepending
                prepending_by_as[prepended_as] = (
                    prepending_by_as.get(prepended_as, 0) + 1
                )

        report.prepending_count = len(report.prepending_routes)
        report.prepending_by_as = prepending_by_as

    @staticmethod
    def _analyze_route_age(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Analyze route ages to identify stable vs. unstable routes.

        Route age indicates how long a route has been in the routing table.
        This analysis helps identify:
        * Stable routes (old age, unlikely to flap)
        * Recently learned routes (potential instability)
        * Age distribution across the RIB

        Age is measured in seconds from the RouteInfo.age field.

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        if not routes:
            return

        # Collect all ages
        ages: List[Tuple[str, int]] = []
        for route in routes:
            age = route.age if route.age is not None else 0
            ages.append((route.prefix, age))

        if not ages:
            return

        # Extract just the age values for statistics
        age_values = [age for _, age in ages]

        # Basic stats
        report.route_age_stats.oldest_age = max(age_values)
        report.route_age_stats.newest_age = min(age_values)
        report.route_age_stats.avg_age = sum(age_values) / len(age_values)

        # Median
        sorted_ages = sorted(age_values)
        mid = len(sorted_ages) // 2
        if len(sorted_ages) % 2 == 0:
            report.route_age_stats.median_age = (
                sorted_ages[mid - 1] + sorted_ages[mid]
            ) // 2
        else:
            report.route_age_stats.median_age = sorted_ages[mid]

        # Time-based buckets (in seconds)
        ONE_MINUTE = 60
        ONE_HOUR = 60 * 60
        ONE_DAY = 24 * 60 * 60

        for age in age_values:
            if age < ONE_MINUTE:
                report.route_age_stats.routes_under_1min += 1
            if age < ONE_HOUR:
                report.route_age_stats.routes_under_1hr += 1
            if age < ONE_DAY:
                report.route_age_stats.routes_under_1day += 1
            else:
                report.route_age_stats.routes_over_1day += 1

        # Find newest routes (sorted by age ascending)
        sorted_by_age = sorted(ages, key=lambda x: x[1])
        report.newest_routes = sorted_by_age[:5]

        # Find oldest routes (sorted by age descending)
        sorted_by_age_desc = sorted(ages, key=lambda x: x[1], reverse=True)
        report.oldest_routes = sorted_by_age_desc[:5]

    @staticmethod
    def _analyze_prefix_length(routes: List[RouteInfo], report: AnalysisReport) -> None:
        """
        Analyze the distribution of prefix lengths in the RIB.

        Prefix length distribution helps identify:
        * Overly specific routes (potential FIB exhaustion)
        * Aggregate routes (summarization)
        * IPv4 vs IPv6 distribution

        IPv4 specific: /28-/32 (very specific)
        IPv4 aggregate: /8-/16 (summarized)
        IPv6 specific: /124-/128
        IPv6 aggregate: /32-/48

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        if not routes:
            return

        # Map: prefix_len -> list of prefixes
        length_map: Dict[int, List[str]] = {}
        total_routes = len(routes)

        for route in routes:
            prefix = route.prefix
            if "/" not in prefix:
                continue

            try:
                prefix_len = int(prefix.split("/")[1])
            except (ValueError, IndexError):
                continue

            if prefix_len not in length_map:
                length_map[prefix_len] = []

            if len(length_map[prefix_len]) < _MAX_PREFIXES_PER_GROUP:
                length_map[prefix_len].append(prefix)

        # Convert to PrefixLengthGroup objects
        specific_count = 0
        aggregate_count = 0

        for prefix_len, prefixes in length_map.items():
            count = len(prefixes)
            percentage = (count / total_routes) * 100 if total_routes > 0 else 0

            # Determine if specific or aggregate (IPv4 heuristics)
            is_specific = prefix_len >= 28
            is_aggregate = prefix_len <= 16

            if is_specific:
                specific_count += count
            if is_aggregate:
                aggregate_count += count

            report.prefix_length_groups.append(
                PrefixLengthGroup(
                    prefix_len=prefix_len,
                    count=count,
                    percentage=round(percentage, 1),
                    prefixes=prefixes,
                    is_specific=is_specific,
                    is_aggregate=is_aggregate,
                )
            )

        # Sort by count descending
        report.prefix_length_groups.sort(key=lambda g: g.count, reverse=True)

        # Build summary dict
        report.prefix_length_summary = {
            g.prefix_len: g.count for g in report.prefix_length_groups
        }

        # Set aggregate counts
        report.specific_routes_count = specific_count
        report.aggregate_routes_count = aggregate_count

    @staticmethod
    def _analyze_prefix_coverage(
        routes: List[RouteInfo], report: AnalysisReport
    ) -> None:
        """
        Analyze prefix coverage for special address ranges.

        Identifies routes matching special address categories:
        * Default routes: 0.0.0.0/0 (IPv4) and ::/0 (IPv6)
        * RFC1918 private: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
        * Link-local: 169.254.0.0/16 (IPv4), fe80::/10 (IPv6)
        * Loopback: 127.0.0.0/8 (IPv4), ::1/128 (IPv6)
        * Bogons: Reserved/unallocated IANA blocks

        This helps identify:
        * Missing default route (connectivity issue)
        * Unexpected private routes in public RIB
        * Potential security issues (bogons)

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        # RFC1918 private address ranges (IPv4)
        RFC1918_RANGES = [
            (ip_to_int("10.0.0.0"), ip_to_int("10.255.255.255")),
            (ip_to_int("172.16.0.0"), ip_to_int("172.31.255.255")),
            (ip_to_int("192.168.0.0"), ip_to_int("192.168.255.255")),
        ]

        # Link-local range (IPv4)
        LINK_LOCAL_RANGE = (ip_to_int("169.254.0.0"), ip_to_int("169.254.255.255"))

        # Loopback range (IPv4)
        LOOPBACK_RANGE = (ip_to_int("127.0.0.0"), ip_to_int("127.255.255.255"))

        # Common bogon ranges (simplified list)
        BOGON_RANGES = [
            (ip_to_int("0.0.0.0"), ip_to_int("0.255.255.255")),  # This network
            (ip_to_int("192.0.2.0"), ip_to_int("192.0.2.255")),  # TEST-NET-1
            (ip_to_int("198.51.100.0"), ip_to_int("198.51.100.255")),  # TEST-NET-2
            (ip_to_int("203.0.113.0"), ip_to_int("203.0.113.255")),  # TEST-NET-3
            (ip_to_int("224.0.0.0"), ip_to_int("239.255.255.255")),  # Multicast
            (ip_to_int("240.0.0.0"), ip_to_int("255.255.255.255")),  # Reserved
        ]

        coverage = report.prefix_coverage

        for route in routes:
            prefix = route.prefix
            if "/" not in prefix:
                continue

            try:
                addr_str, mask_str = prefix.split("/")
                prefix_len = int(mask_str)
            except (ValueError, IndexError):
                continue

            # Check for default routes
            if prefix == "0.0.0.0/0":
                coverage.has_default_ipv4 = True
                continue
            if prefix == "::/0":
                coverage.has_default_ipv6 = True
                continue

            # Only check IPv4 addresses for the following categories
            if ":" in addr_str:
                continue  # Skip IPv6 for now

            try:
                addr_int = ip_to_int(addr_str)
            except (ValueError, OSError):
                continue

            # Check RFC1918
            for start, end in RFC1918_RANGES:
                if start <= addr_int <= end:
                    coverage.rfc1918_routes.append(prefix)
                    coverage.rfc1918_count += 1
                    break

            # Check link-local
            if LINK_LOCAL_RANGE[0] <= addr_int <= LINK_LOCAL_RANGE[1]:
                coverage.link_local_routes.append(prefix)
                coverage.link_local_count += 1

            # Check loopback
            if LOOPBACK_RANGE[0] <= addr_int <= LOOPBACK_RANGE[1]:
                coverage.loopback_routes.append(prefix)
                coverage.loopback_count += 1

            # Check bogons (only for non-private, non-loopback)
            for start, end in BOGON_RANGES:
                if start <= addr_int <= end:
                    coverage.bogon_routes.append(prefix)
                    coverage.bogon_count += 1
                    break

    @classmethod
    def _analyze_bgp_attributes(
        cls, routes: List[RouteInfo], report: AnalysisReport
    ) -> None:
        """
        Detect BGP routes whose attributes deviate from the expected defaults.

        Pass 4 of 4.

        Three categories are checked:

        * **Local-Pref** – any value != :attr:`DEFAULT_LOCAL_PREF` (100).
          A non-default LP is flagged as *critical* because it directly
          influences best-path selection within the AS.
        * **MED** – any value != :attr:`DEFAULT_MED` (0).  Non-zero MEDs
          influence path selection at AS boundaries and may indicate active
          traffic-engineering policy.
        * **Communities** – presence of any community strings.  These carry
          routing policy signals that can affect propagation or filtering
          at peers and route-servers.

        Attribute values are normalised to ``int`` before comparison so that
        string ``"100"`` and integer ``100`` are treated the same.  Routes with
        unparseable attribute values are silently skipped to avoid crashing on
        malformed RIB data.

        Args:
            routes: All routes in the RIB.
            report: Report object to update in place.
        """
        bgp_routes = [r for r in routes if r.protocol.upper() == "BGP"]

        for route in bgp_routes:
            # ---- Local-Pref check ----------------------------------------
            if route.local_pref is not None:
                try:
                    if int(route.local_pref) != cls.DEFAULT_LOCAL_PREF:
                        report.non_default_lp.append(
                            BGPAttributeAnomaly(
                                prefix=route.prefix,
                                attribute="Local-Pref",
                                value=str(route.local_pref),
                                default_value=str(cls.DEFAULT_LOCAL_PREF),
                                route=route,
                            )
                        )
                except (ValueError, TypeError):
                    # Unparseable local_pref; skip without crashing.
                    pass

            # ---- MED check -----------------------------------------------
            if route.med is not None:
                try:
                    if int(route.med) != cls.DEFAULT_MED:
                        report.non_default_med.append(
                            BGPAttributeAnomaly(
                                prefix=route.prefix,
                                attribute="MED",
                                value=str(route.med),
                                default_value=str(cls.DEFAULT_MED),
                                route=route,
                            )
                        )
                except (ValueError, TypeError):
                    # Unparseable MED; skip without crashing.
                    pass

            # ---- Communities check ---------------------------------------
            if route.communities:
                # Store up to 5 community strings in the anomaly for display;
                # the full set is accessible via route.communities on the
                # attached RouteInfo object.
                report.with_communities.append(
                    BGPAttributeAnomaly(
                        prefix=route.prefix,
                        attribute="Communities",
                        value="|".join(route.communities[:5]),
                        default_value="none",
                        route=route,
                    )
                )

    # ------------------------------------------------------------------
    # Public query helpers  (operate on a previously returned AnalysisReport)
    # ------------------------------------------------------------------

    @staticmethod
    def get_routes_by_origin(report: AnalysisReport, origin_as: str) -> List[str]:
        """
        Return the stored prefix list for a given origin AS.

        The returned list may be truncated at :data:`_MAX_PREFIXES_PER_GROUP`
        entries.  To check whether truncation occurred, inspect the
        ``prefixes_truncated`` flag on the :class:`OriginASGroup`, or compare
        the list length against the group's ``count`` field.

        Args:
            report:    A :class:`AnalysisReport` previously returned by
                       :meth:`analyze`.
            origin_as: The origin AS identifier string (e.g. ``"65001"``), or
                       ``"Local"`` to retrieve self-originated routes.

        Returns:
            List of prefix strings (CIDR notation), possibly empty if the AS
            was not found in the report.
        """
        if origin_as == "Local":
            # Self-originated routes live in their own dedicated group.
            return report.self_originated.prefixes

        group = next(
            (g for g in report.origin_groups if g.origin_as == origin_as),
            None,
        )
        return group.prefixes if group else []

    @staticmethod
    def get_summary_text(report: AnalysisReport) -> str:
        """
        Build a concise multi-line human-readable summary of *report*.

        Lines for non-default LP, MED, and communities are omitted when the
        corresponding lists are empty so the output is not cluttered with
        zero-count entries.

        Args:
            report: A :class:`AnalysisReport` previously returned by
                    :meth:`analyze`.

        Returns:
            A newline-separated string suitable for logging or CLI display.

        Example output::

            Routes : 42000 total, 41998 active, 42000 BGP
            AS Paths: 39500 unique, 8200 origins
            Avg path length: 3.4  (min 1, max 12)
            Self-originated : 12
            Non-default LP  : 304
            Non-default MED : 87
            With communities: 15200
        """
        s = report.as_path_stats  # local alias for readability

        lines: List[str] = [
            (
                f"Routes : {report.total_routes} total, "
                f"{report.active_routes} active, "
                f"{report.bgp_routes} BGP"
            ),
            (f"AS Paths: {s.unique_paths} unique, {s.unique_origins} origins"),
            (
                f"Avg path length: {s.avg_path_length:.1f}  "
                f"(min {s.min_path_length}, max {s.max_path_length})"
            ),
        ]

        # Only append optional lines when counts are non-zero to keep the
        # output clean for tables that have no anomalies.
        if report.self_originated.count:
            lines.append(f"Self-originated : {report.self_originated.count}")

        if report.non_default_lp:
            lines.append(f"Non-default LP  : {len(report.non_default_lp)}")

        if report.non_default_med:
            lines.append(f"Non-default MED : {len(report.non_default_med)}")

        if report.with_communities:
            lines.append(f"With communities: {len(report.with_communities)}")

        return "\n".join(lines)
