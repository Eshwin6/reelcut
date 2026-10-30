# ReelCut setup for a Windows PC: Docker Desktop + Tailscale + the ReelCut container.
#
# Run in PowerShell *as Administrator*:
#   irm https://raw.githubusercontent.com/Eshwin6/reelcut/main/windows/setup.ps1 | iex
#
# Run the same command again any time to update to the latest code.
# Your brands, music, accounts and videos live in a Docker volume and are kept.

$ErrorActionPreference = "Continue"
$Raw = "https://raw.githubusercontent.com/Eshwin6/reelcut/main/windows"
$Dir = Join-Path $env:USERPROFILE "reelcut"
$TS = "C:\Program Files\Tailscale\tailscale.exe"
$DockerApp = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Magenta }
function Stop-With($m) { Write-Host "`n$m" -ForegroundColor Yellow; throw "stopped" }
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

try {
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Stop-With "Open PowerShell as Administrator (Start menu > type PowerShell > right-click > Run as administrator) and paste the command again."
    }
    if (-not (Has winget)) {
        Stop-With "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again."
    }

    Step "Installing Docker Desktop and Tailscale (anything already installed is skipped)"
    foreach ($id in "Docker.DockerDesktop", "Tailscale.Tailscale") {
        winget list --id $id -e --accept-source-agreements | Out-Null
        if ($LASTEXITCODE -ne 0) {
            winget install --id $id -e --accept-source-agreements --accept-package-agreements
        }
    }
    Refresh-Path

    Step "Starting Docker"
    if (-not (Has docker)) {
        Stop-With "Docker was just installed. Restart your PC, open Docker Desktop once and accept its terms, then run this command again."
    }
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path $DockerApp) { Start-Process $DockerApp }
        Write-Host "Waiting for Docker to start (the first time can take a few minutes)..."
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 5
            docker info 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
        }
        if ($LASTEXITCODE -ne 0) {
            Stop-With "Docker didn't start. Open Docker Desktop and finish its setup (it may ask to install WSL and restart), then run this again."
        }
    }

    Step "Getting ReelCut files into $Dir"
    New-Item -ItemType Directory -Force $Dir | Out-Null
    Set-Location $Dir
    foreach ($f in "Dockerfile", "docker-compose.yml") {
        Invoke-WebRequest "$Raw/$f" -OutFile $f -UseBasicParsing
    }
    if (-not (Test-Path .env)) {
        $pw = Read-Host "Choose a password for the ReelCut app"
        "APP_PASSWORD=$pw" | Set-Content .env -Encoding ascii
    }

    Step "Connecting Tailscale (log in in the browser window if one opens)"
    if (-not (Test-Path $TS)) { Stop-With "Tailscale didn't install. Install it from tailscale.com/download and run this again." }
    & $TS up
    $hostName = ((& $TS status --json) | Out-String | ConvertFrom-Json).Self.DNSName.TrimEnd(".")
    if (-not $hostName) { Stop-With "Couldn't read this PC's Tailscale name. Make sure you're logged in to Tailscale and run this again." }
    $url = "https://$hostName"

    Write-Host ""
    Write-Host "Auto-posting needs Instagram and TikTok to reach the app, which means a public https link."
    Write-Host "The app stays protected by your password. Without it, the app only opens on your own Tailscale devices."
    $answer = Read-Host "Make it reachable for auto-posting? [Y/n]"
    $public = $answer -notmatch '^[nN]'

    # The app needs to know its own address for Instagram/TikTok logins and video links.
    $lines = @(Get-Content .env | Where-Object { $_ -notmatch '^PUBLIC_BASE_URL=' })
    $lines += "PUBLIC_BASE_URL=$url"
    $lines | Set-Content .env -Encoding ascii

    Step "Building and starting ReelCut (the first build takes 5-15 minutes)"
    $env:CACHEBUST = Get-Date -Format "yyyyMMddHHmmss"
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { Stop-With "The build failed. Copy the error text above and send it to Claude." }

    Step "Publishing it through Tailscale"
    if ($public) {
        Write-Host "If Tailscale prints a link to enable Funnel, open it, click Enable, then come back here."
        & $TS funnel --bg 7860
    } else {
        & $TS serve --bg 7860
    }

    Write-Host "`nReelCut is running at:  $url" -ForegroundColor Green
    if ($public) {
        Write-Host "Open that link on your phone in any browser, then Share > Add to Home Screen."
    } else {
        Write-Host "On your phone: install the Tailscale app, log in with the same account, then open that link"
        Write-Host "and use Share > Add to Home Screen."
    }
    Write-Host "Keep this PC on and awake, and leave Docker Desktop set to start when you sign in."
    Write-Host "To update later, run the same command again."
} catch {
    if ("$_" -ne "stopped") { Write-Host "`nSomething went wrong: $_`nSend this to Claude." -ForegroundColor Red }
}
