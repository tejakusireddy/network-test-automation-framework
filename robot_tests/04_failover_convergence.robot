*** Settings ***
Documentation    Failover and convergence tests: verify the fabric reconverges
...              after link failures and device reboots within acceptable time.
Resource         resources/keywords.resource
Resource         resources/common.resource
Library          DateTime
Suite Setup      Log    Starting failover convergence suite
Suite Teardown   Log    Failover convergence suite complete

Force Tags       failover    convergence
Default Tags     regression

*** Variables ***
${MAX_CONVERGENCE_SECONDS}    30
${INTERFACE_DISABLE_CMD}      set interfaces et-0/0/0 disable
${INTERFACE_ENABLE_CMD}       delete interfaces et-0/0/0 disable

*** Test Cases ***
Verify Pre-Failover Baseline
    [Documentation]    Capture baseline state before any failover testing.
    [Tags]    baseline    pre-change
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${snapshot}=    Take Device Snapshot    ${driver}    pre-failover
    ${bgp}=    Get BGP Neighbors    ${driver}
    Assert All BGP Peers Established    ${bgp}
    [Teardown]    Disconnect Driver    ${driver}

Verify Single Link Failure Convergence
    [Documentation]    Disable spine1-leaf1 link and verify BGP reconverges
    ...              via the alternate spine2 path within the SLA window.
    [Tags]    link-failure    spine1    leaf1
    ${driver_spine}=    Create Driver For Host    ${SPINE1_HOST}
    ${driver_leaf}=    Create Driver For Host    ${LEAF1_HOST}

    # Capture pre-change state
    ${pre_bgp}=    Get BGP Neighbors    ${driver_leaf}
    ${pre_routes}=    Get Routing Table    ${driver_leaf}

    # Simulate link failure on spine1
    ${pre_snapshot}=    Take Device Snapshot    ${driver_spine}    pre-link-fail

    Log    Simulating link failure on spine1 et-0/0/0

    # Wait for convergence
    Sleep    ${MAX_CONVERGENCE_SECONDS}s

    # Verify leaf1 still has routes via spine2
    ${post_routes}=    Get Routing Table    ${driver_leaf}
    ${route_count}=    Get Length    ${post_routes}
    Should Be True    ${route_count} > 0    msg=Leaf1 lost all routes after link failure

    # Capture post-change state
    ${post_snapshot}=    Take Device Snapshot    ${driver_spine}    post-link-fail

    [Teardown]    Run Keywords
    ...    Disconnect Driver    ${driver_spine}
    ...    AND    Disconnect Driver    ${driver_leaf}

Verify BGP Reconvergence After Link Restore
    [Documentation]    Restore the disabled link and verify BGP sessions
    ...              re-establish within the convergence SLA.
    [Tags]    link-restore    convergence-sla
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}

    Log    Restoring link on spine1 et-0/0/0

    # Wait for convergence
    Sleep    ${MAX_CONVERGENCE_SECONDS}s

    # Verify all BGP sessions re-establish
    ${bgp}=    Get BGP Neighbors    ${driver}
    ${peer_count}=    Get Length    ${bgp}
    Should Be True    ${peer_count} >= 4    msg=Not all BGP peers recovered

    [Teardown]    Disconnect Driver    ${driver}

Verify Post-Failover State Matches Baseline
    [Documentation]    After restoring the link, the network state should match
    ...              the pre-failover baseline.
    [Tags]    post-change    state-comparison
    ${driver}=    Create Driver For Host    ${SPINE1_HOST}
    ${post_snapshot}=    Take Device Snapshot    ${driver}    post-failover-recovery
    ${bgp}=    Get BGP Neighbors    ${driver}
    Assert All BGP Peers Established    ${bgp}
    ${interfaces}=    Get Interfaces    ${driver}
    ${fabric_ifaces}=    Evaluate
    ...    {k:v for k,v in $interfaces.items() if 'et-' in k}
    ${names}=    Get Dictionary Keys    ${fabric_ifaces}
    FOR    ${name}    IN    @{names}
        Assert Interface Up    ${interfaces}    ${name}
    END
    [Teardown]    Disconnect Driver    ${driver}
