$ErrorActionPreference = "Stop"

# Realtime contest dashboard. Keep port 8787 for tools\ai_proxy.py.
$env:DASHBOARD_HOST = "0.0.0.0"
$env:DASHBOARD_PORT = "8790"

Set-Location (Split-Path -Parent $PSScriptRoot)
py tools\dashboard_server.py --host $env:DASHBOARD_HOST --port $env:DASHBOARD_PORT
