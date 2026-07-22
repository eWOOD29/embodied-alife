[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$groupName = "Embodied Artificial Life"

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell window."
}

$rules = @(Get-NetFirewallRule -Group $groupName -ErrorAction SilentlyContinue)
if ($rules.Count -eq 0) {
    Write-Host "No Embodied Artificial Life firewall rules were found."
    exit 0
}

$rules | Remove-NetFirewallRule
Write-Host "Removed Embodied Artificial Life Tailscale firewall rules."
