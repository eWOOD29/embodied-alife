[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8797
)

$ErrorActionPreference = "Stop"
$groupName = "Embodied Artificial Life"
$rulePrefix = "Embodied Artificial Life (Tailscale)"

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell window."
}

Get-NetFirewallRule -Group $groupName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

$tailscaleAdapters = @(
    Get-NetAdapter -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match "Tailscale" -or $_.InterfaceDescription -match "Tailscale"
        } |
        Select-Object -ExpandProperty Name -Unique
)

$common = @{
    Group        = $groupName
    Direction    = "Inbound"
    Action       = "Allow"
    Enabled      = "True"
    Protocol     = "TCP"
    LocalPort    = $Port
    Profile      = "Any"
}

if ($tailscaleAdapters.Count -gt 0) {
    $common["InterfaceAlias"] = $tailscaleAdapters
    Write-Host "Restricting rules to Tailscale adapter(s): $($tailscaleAdapters -join ', ')"
} else {
    Write-Warning "No Tailscale adapter was detected. Rules will still be restricted to Tailscale address ranges."
}

$ipv4 = $common.Clone()
$ipv4["DisplayName"] = "$rulePrefix IPv4"
$ipv4["RemoteAddress"] = "100.64.0.0/10"
New-NetFirewallRule @ipv4 | Out-Null

$ipv6 = $common.Clone()
$ipv6["DisplayName"] = "$rulePrefix IPv6"
$ipv6["RemoteAddress"] = "fd7a:115c:a1e0::/48"
New-NetFirewallRule @ipv6 | Out-Null

Write-Host "Allowed inbound TCP $Port from Tailscale IPv4 and IPv6 addresses."
Write-Host "The application must be running with HOST=0.0.0.0."
Write-Host "Remove these rules with: scripts\disable-tailscale-access.ps1"
