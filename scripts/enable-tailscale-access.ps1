[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8797
)

$ErrorActionPreference = "Stop"
$groupName = "Embodied Artificial Life"
$rulePrefix = "Embodied Artificial Life (Tailscale)"
$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot ".env"

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell window."
}

if (-not (Test-Path -LiteralPath $envPath)) {
    $examplePath = Join-Path $projectRoot ".env.example"
    if (-not (Test-Path -LiteralPath $examplePath)) {
        throw "Neither .env nor .env.example was found in $projectRoot."
    }
    Copy-Item -LiteralPath $examplePath -Destination $envPath
}

$envLines = @(Get-Content -LiteralPath $envPath)
$hostFound = $false
$envLines = @(
    foreach ($line in $envLines) {
        if ($line -match '^\s*HOST\s*=') {
            'HOST=0.0.0.0'
            $hostFound = $true
        } else {
            $line
        }
    }
)
if (-not $hostFound) {
    $envLines = @('HOST=0.0.0.0') + $envLines
}
Set-Content -LiteralPath $envPath -Value $envLines -Encoding UTF8

Get-NetFirewallRule -Group $groupName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

$common = @{
    Group        = $groupName
    Direction    = "Inbound"
    Action       = "Allow"
    Enabled      = "True"
    Protocol     = "TCP"
    LocalPort    = $Port
    LocalAddress = "Any"
    Profile      = "Any"
}

$ipv4 = $common.Clone()
$ipv4["DisplayName"] = "$rulePrefix IPv4"
$ipv4["RemoteAddress"] = "100.64.0.0/10"
New-NetFirewallRule @ipv4 | Out-Null

$ipv6 = $common.Clone()
$ipv6["DisplayName"] = "$rulePrefix IPv6"
$ipv6["RemoteAddress"] = "fd7a:115c:a1e0::/48"
New-NetFirewallRule @ipv6 | Out-Null

Write-Host "Set HOST=0.0.0.0 in $envPath."
Write-Host "Allowed inbound TCP $Port from Tailscale IPv4 and IPv6 addresses."
Write-Host "Stop and restart Embodied Artificial Life before testing remote access."
Write-Host "After restart, verify with: Get-NetTCPConnection -LocalPort $Port -State Listen"
Write-Host "Remove these rules with: scripts\disable-tailscale-access.ps1"