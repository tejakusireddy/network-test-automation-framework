*** Settings ***
Documentation    Topology validation: verify LLDP adjacencies and physical connectivity
...              across the leaf-spine fabric.
Resource         resources/keywords.resource
Resource         resources/common.resource
Suite Setup      Log    Starting topology validation suite
Suite Teardown   Log    Topology validation suite complete

Force Tags       topology    lldp    smoke
Default Tags     regression

*** Test Cases ***
Verify Spine1 LLDP Neighbors
    [Documentation]    Spine1 should see LLDP neighbors on all downlinks to leaves.
    [Tags]    spine    spine1
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${lldp}=    Get LLDP Neighbors    ${driver}
    ${count}=    Get Length    ${lldp}
    Should Be True    ${count} >= 4    msg=Spine1 has ${count} LLDP neighbors, expected >= 4
    [Teardown]    Disconnect Driver    ${driver}

Verify Spine2 LLDP Neighbors
    [Documentation]    Spine2 should see LLDP neighbors on all downlinks to leaves.
    [Tags]    spine    spine2
    ${driver}=    Create Driver For Host    ${SPINE2_HOST}
    ${lldp}=    Get LLDP Neighbors    ${driver}
    ${count}=    Get Length    ${lldp}
    Should Be True    ${count} >= 4    msg=Spine2 has ${count} LLDP neighbors, expected >= 4
    [Teardown]    Disconnect Driver    ${driver}

Verify Leaf1 Uplinks to Spines
    [Documentation]    Leaf1 should have LLDP adjacency to both spine switches.
    [Tags]    leaf    leaf1
    ${driver}=    Create Driver For Host    ${LEAF1_HOST}
    ${lldp}=    Get LLDP Neighbors    ${driver}
    ${neighbors}=    Evaluate    [v.get('remote_system','') for v in $lldp.values()]
    Should Contain    ${neighbors}    spine1    msg=Leaf1 missing LLDP neighbor spine1
    Should Contain    ${neighbors}    spine2    msg=Leaf1 missing LLDP neighbor spine2
    [Teardown]    Disconnect Driver    ${driver}

Verify All Fabric Interfaces Are Up
    [Documentation]    All fabric-facing interfaces on spine1 should be operationally up.
    [Tags]    interfaces    spine1
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${interfaces}=    Get Interfaces    ${driver}
    ${fabric_ifaces}=    Evaluate
    ...    {k:v for k,v in $interfaces.items() if 'et-' in k or 'Ethernet' in k}
    ${names}=    Get Dictionary Keys    ${fabric_ifaces}
    FOR    ${name}    IN    @{names}
        Assert Interface Up    ${interfaces}    ${name}
    END
    [Teardown]    Disconnect Driver    ${driver}

Verify Spine1 Health Check Passes
    [Documentation]    Run a comprehensive health check on spine1.
    [Tags]    health    spine1
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${report}=    Run Health Check    ${driver}
    ${healthy}=    Get From Dictionary    ${report}    overall_healthy
    Should Be True    ${healthy}    msg=Spine1 health check failed
    [Teardown]    Disconnect Driver    ${driver}
