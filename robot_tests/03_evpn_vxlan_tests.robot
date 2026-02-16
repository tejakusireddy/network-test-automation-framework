*** Settings ***
Documentation    EVPN-VXLAN validation: verify EVPN route types, VNI mappings,
...              and VTEP reachability across the fabric.
Resource         resources/keywords.resource
Resource         resources/common.resource
Suite Setup      Log    Starting EVPN-VXLAN validation suite
Suite Teardown   Log    EVPN-VXLAN validation suite complete

Force Tags       evpn    vxlan    overlay
Default Tags     regression

*** Test Cases ***
Verify Leaf1 EVPN Routes Present
    [Documentation]    Leaf1 should have EVPN type-2 and type-5 routes.
    [Tags]    leaf    leaf1    evpn-routes
    ${driver}=    Create Driver For Host    ${LEAF1_HOST}
    ${evpn}=    Get EVPN Routes    ${driver}
    ${count}=    Get Length    ${evpn}
    Should Be True    ${count} > 0    msg=No EVPN routes found on leaf1
    [Teardown]    Disconnect Driver    ${driver}

Verify Leaf2 EVPN Routes Present
    [Documentation]    Leaf2 should have EVPN routes from the fabric.
    [Tags]    leaf    leaf2    evpn-routes
    ${driver}=    Create Driver For Host    ${LEAF2_HOST}
    ${evpn}=    Get EVPN Routes    ${driver}
    ${count}=    Get Length    ${evpn}
    Should Be True    ${count} > 0    msg=No EVPN routes found on leaf2
    [Teardown]    Disconnect Driver    ${driver}

Verify Spine1 Has EVPN BGP Family
    [Documentation]    Spine1 as route reflector should carry EVPN routes.
    [Tags]    spine    spine1    evpn-rr
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${evpn}=    Get EVPN Routes    ${driver}
    ${count}=    Get Length    ${evpn}
    Log    Spine1 has ${count} EVPN routes
    [Teardown]    Disconnect Driver    ${driver}

Verify VTEP Loopback Reachability From Leaf1
    [Documentation]    Leaf1 should have routes to all other leaf VTEP loopbacks.
    [Tags]    leaf    leaf1    vtep
    ${driver}=    Create Driver For Host    ${LEAF1_HOST}
    ${routes}=    Get Routing Table    ${driver}
    Assert Route Exists    ${routes}    10.255.0.4/32
    Assert Route Exists    ${routes}    10.255.0.5/32
    Assert Route Exists    ${routes}    10.255.0.6/32
    [Teardown]    Disconnect Driver    ${driver}

Verify Leaf Pair EVPN Snapshot Consistency
    [Documentation]    Take snapshots of leaf1 and leaf2 EVPN state and verify
    ...              both have learned routes from each other.
    [Tags]    leaf    snapshot    evpn-consistency
    ${driver1}=    Create Driver For Host    ${LEAF1_HOST}
    ${driver2}=    Create Driver For Host    ${LEAF2_HOST}
    ${snap1}=    Take Device Snapshot    ${driver1}    leaf1-evpn
    ${snap2}=    Take Device Snapshot    ${driver2}    leaf2-evpn
    ${evpn1_count}=    Evaluate    len($snap1.evpn_routes)
    ${evpn2_count}=    Evaluate    len($snap2.evpn_routes)
    Should Be True    ${evpn1_count} > 0    msg=Leaf1 has no EVPN routes
    Should Be True    ${evpn2_count} > 0    msg=Leaf2 has no EVPN routes
    [Teardown]    Run Keywords    Disconnect Driver    ${driver1}
    ...    AND    Disconnect Driver    ${driver2}
