*** Settings ***
Documentation    Reusable keywords wrapping the Python automation framework.
Library          Collections
Library          ../../src/drivers/driver_factory.py
Library          ../../src/core/validator.py
Library          ../../src/core/snapshot_engine.py
Resource         common.resource

*** Keywords ***
Create Driver For Host
    [Documentation]    Create and connect a vendor driver for the given host.
    [Arguments]    ${hostname}    ${vendor}=${VENDOR}    ${platform}=${PLATFORM}
    ...            ${username}=${DEVICE_USER}    ${password}=${DEVICE_PASS}    ${port}=${DEVICE_PORT}
    ${host_data}=    Create Dictionary
    ...    hostname=${hostname}
    ...    vendor=${vendor}
    ...    platform=${platform}
    ...    username=${username}
    ...    password=${password}
    ...    port=${port}
    ${factory}=    Evaluate    __import__('src.drivers.driver_factory', fromlist=['DriverFactory']).DriverFactory()
    ${driver}=    Call Method    ${factory}    create_from_dict    ${host_data}
    Call Method    ${driver}    connect
    RETURN    ${driver}

Disconnect Driver
    [Documentation]    Safely disconnect a driver.
    [Arguments]    ${driver}
    Call Method    ${driver}    disconnect

Get BGP Neighbors
    [Documentation]    Retrieve BGP neighbor table from a connected driver.
    [Arguments]    ${driver}
    ${neighbors}=    Call Method    ${driver}    get_bgp_neighbors
    RETURN    ${neighbors}

Get Interfaces
    [Documentation]    Retrieve interface table from a connected driver.
    [Arguments]    ${driver}
    ${interfaces}=    Call Method    ${driver}    get_interfaces
    RETURN    ${interfaces}

Get Routing Table
    [Documentation]    Retrieve routing table from a connected driver.
    [Arguments]    ${driver}
    ${routes}=    Call Method    ${driver}    get_routing_table
    RETURN    ${routes}

Get LLDP Neighbors
    [Documentation]    Retrieve LLDP neighbor table from a connected driver.
    [Arguments]    ${driver}
    ${lldp}=    Call Method    ${driver}    get_lldp_neighbors
    RETURN    ${lldp}

Get EVPN Routes
    [Documentation]    Retrieve EVPN route table from a connected driver.
    [Arguments]    ${driver}
    ${evpn}=    Call Method    ${driver}    get_evpn_routes
    RETURN    ${evpn}

Take Device Snapshot
    [Documentation]    Capture a full state snapshot from a device.
    [Arguments]    ${driver}    ${snapshot_id}
    ${snapshot}=    Call Method    ${driver}    take_snapshot    ${snapshot_id}
    RETURN    ${snapshot}

Run Health Check
    [Documentation]    Run a comprehensive health check on a device.
    [Arguments]    ${driver}
    ${report}=    Call Method    ${driver}    run_health_check
    RETURN    ${report}

Assert BGP Peer Established
    [Documentation]    Verify a specific BGP peer is in Established state.
    [Arguments]    ${bgp_data}    ${peer_address}
    ${peer}=    Get From Dictionary    ${bgp_data}    ${peer_address}
    ${state}=    Get From Dictionary    ${peer}    state
    Should Be Equal As Strings    ${state}    established
    ...    msg=BGP peer ${peer_address} is ${state}, expected established

Assert All BGP Peers Established
    [Documentation]    Verify all BGP peers are in Established state.
    [Arguments]    ${bgp_data}
    ${peers}=    Get Dictionary Keys    ${bgp_data}
    FOR    ${peer}    IN    @{peers}
        Assert BGP Peer Established    ${bgp_data}    ${peer}
    END

Assert Interface Up
    [Documentation]    Verify a specific interface is operationally up.
    [Arguments]    ${interface_data}    ${interface_name}
    ${iface}=    Get From Dictionary    ${interface_data}    ${interface_name}
    ${status}=    Get From Dictionary    ${iface}    oper_status
    Should Be Equal As Strings    ${status}    up
    ...    msg=Interface ${interface_name} is ${status}, expected up

Assert Route Exists
    [Documentation]    Verify a route exists in the routing table.
    [Arguments]    ${routing_data}    ${prefix}
    Dictionary Should Contain Key    ${routing_data}    ${prefix}
    ...    msg=Route ${prefix} not found in routing table
