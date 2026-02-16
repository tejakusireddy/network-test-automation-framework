*** Settings ***
Documentation    Common settings and variables shared across all test suites.
Library          Collections
Library          String
Library          OperatingSystem
Library          BuiltIn

*** Variables ***
${SPINE1_HOST}         172.20.20.2
${SPINE2_HOST}         172.20.20.3
${LEAF1_HOST}          172.20.20.4
${LEAF2_HOST}          172.20.20.5
${LEAF3_HOST}          172.20.20.6
${LEAF4_HOST}          172.20.20.7
${WAN_EDGE_HOST}       172.20.20.8

${DEVICE_USER}         admin
${DEVICE_PASS}         admin123
${DEVICE_PORT}         830
${VENDOR}              juniper
${PLATFORM}            junos

${BGP_AS}              65000
${OSPF_AREA}           0.0.0.0
${EVPN_VNI_BASE}       10000
${BFD_MIN_INTERVAL}    300
