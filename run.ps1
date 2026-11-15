param([ValidateRange(1, 65535)][int]$Port = 8000, [switch]$Lan)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
$finnPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $finnPython -c 'import fastapi, uvicorn, httpx, bs4, pypdfium2, fontTools' 2>$null
if ($LASTEXITCODE -ne 0) {
    python -m pip --python $finnPython install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$finnBind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$finnPreviousKey = $env:GEMINI_API_KEY
try {
    if ($env:OS -eq 'Windows_NT' -and [string]::IsNullOrWhiteSpace($finnPreviousKey)) {
        foreach ($finnScope in 'User', 'Machine') {
            $finnSavedKey = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', $finnScope)
            if (-not [string]::IsNullOrWhiteSpace($finnSavedKey)) {
                $env:GEMINI_API_KEY = $finnSavedKey
                break
            }
        }
    }
    Write-Host "FINN is starting at http://localhost:$Port. Press Ctrl+C to stop."
    if ($Lan) {
        $finnInterfaces = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()
        $finnAddresses = foreach ($finnInterface in $finnInterfaces) {
            if ($finnInterface.OperationalStatus -ne 'Up' -or
                $finnInterface.NetworkInterfaceType -notin 'Wireless80211', 'Ethernet') { continue }
            $finnProperties = $finnInterface.GetIPProperties()
            $finnGateway = $finnProperties.GatewayAddresses | Where-Object {
                $_.Address.AddressFamily -eq 'InterNetwork' -and
                $_.Address -ne [System.Net.IPAddress]::Any
            }
            if (-not $finnGateway) { continue }
            foreach ($finnAddress in $finnProperties.UnicastAddresses) {
                if ($finnAddress.Address.AddressFamily -eq 'InterNetwork') {
                    Write-Host "Phone on the same trusted Wi-Fi ($($finnInterface.Name)): http://$($finnAddress.Address):$Port"
                    $finnAddress.Address
                }
            }
        }
        if (-not $finnAddresses) {
            Write-Host "Use ipconfig to find the PC's Wi-Fi IPv4 address, then open http://<IPv4-address>:$Port on your phone."
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) {
        Write-Host 'Gemini key loaded. FINN calls Gemini when you choose an AI action.'
    }
    & $finnPython -m uvicorn finn.main:app --host $finnBind --port $Port
} finally {
    $env:GEMINI_API_KEY = $finnPreviousKey
}
