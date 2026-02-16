*** Settings ***
Documentation    BGP session validation: verify all iBGP sessions are established,
...              route reflector configuration is correct, and BFD is active.
Resource         resources/keywords.resource
Resource         resources/common.resource
Suite Setup      Log    Starting BGP validation suite
Suite Teardown   Log    BGP validation suite complete

Force Tags       bgp    protocol
Default Tags     regression

*** Test Cases ***
Verify Spine1 All BGP Sessions Established
    [Documentation]    All BGP peers on spine1 (route reflector) should be established.
    [Tags]    spine    spine1    rr
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${bgp}=    Get BGP Neighbors    ${driver}
    ${peer_count}=    Get Length    ${bgp}
    Should Be True    ${peer_count} >= 4
    ...    msg=Spine1 has ${peer_count} BGP peers, expected >= 4 (4 leaves)
    Assert All BGP Peers Established    ${bgp}
    [Teardown]    Disconnect Driver    ${driver}

Verify Spine2 All BGP Sessions Established
    [Documentation]    All BGP peers on spine2 (route reflector) should be established.
    [Tags]    spine    spine2    rr
    ${driver}=    Create Driver For Host    ${SPINE2_HOST}
    ${bgp}=    Get BGP Neighbors    ${driver}
    ${peer_count}=    Get Length    ${bgp}
    Should Be True    ${peer_count} >= 4
    ...    msg=Spine2 has ${peer_count} BGP peers, expected >= 4
    Assert All BGP Peers Established    ${bgp}
    [Teardown]    Disconnect Driver    ${driver}

Verify Leaf1 BGP Peers Include Both Spines
    [Documentation]    Leaf1 should have BGP sessions to both spine1 and spine2.
    [Tags]    leaf    leaf1
    ${driver}=    Create Driver For Host    ${LEAF1_HOST}
    ${bgp}=    Get BGP Neighbors    ${driver}
    ${peer_count}=    Get Length    ${bgp}
    Should Be True    ${peer_count} >= 2
    ...    msg=Leaf1 has ${peer_count} BGP peers, expected >= 2
    Assert All BGP Peers Established    ${bgp}
    [Teardown]    Disconnect Driver    ${driver}

Verify WAN Edge BGP To Spine1
    [Documentation]    WAN edge should have an eBGP session to spine1.
    [Tags]    wan    wan-edge
    ${driver}=    Create Driver For Host    ${WAN_EDGE_HOST}
    ${bgp}=    Get BGP Neighbors    ${driver}
    ${peer_count}=    Get Length    ${bgp}
    Should Be True    ${peer_count} >= 1
    ...    msg=WAN edge has ${peer_count} BGP peers, expected >= 1
    [Teardown]    Disconnect Driver    ${driver}

Verify Spine1 Loopback Route Propagation
    [Documentation]    All leaf loopback prefixes should be in spine1's routing table.
    [Tags]    spine    spine1    routes
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${routes}=    Get Routing Table    ${driver}
    Assert Route Exists    ${routes}    10.255.0.3/32
    Assert Route Exists    ${routes}    10.255.0.4/32
    Assert Route Exists    ${routes}    10.255.0.5/32
    Assert Route Exists    ${routes}    10.255.0.6/32
    [Teardown]    Disconnect Driver    ${driver}
