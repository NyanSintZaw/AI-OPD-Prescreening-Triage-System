# Start the full on-prem stack on Windows. Ports are defined ONCE, here.
# The bash twin (run-local.sh) stays for the Linux node; keep the two in sync.
#
#   .\run-local.ps1          start everything on one machine
#   .\run-local.ps1 ai       start ONLY the AI node (LLM + speech), bound to
#                            0.0.0.0 so a separate backend machine can reach it
#   .\run-local.ps1 check    just health-check what is already running
#
# Ports match run-local.sh so one .env serves either node.

param([ValidateSet('all', 'ai', 'check')][string]$Mode = 'all')

$ErrorActionPreference = 'Stop'
# Invoke-WebRequest renders a progress bar per call and it costs more than the
# request does; without this every health probe is visibly slower.
$ProgressPreference = 'SilentlyContinue'

$SpeechPort = if ($env:SPEECH_PORT) { $env:SPEECH_PORT } else { 8090 }
$OllamaPort = if ($env:OLLAMA_PORT) { $env:OLLAMA_PORT } else { 11434 }
$ApiPort    = if ($env:API_PORT)    { $env:API_PORT }    else { 8100 }
$WebPort    = if ($env:WEB_PORT)    { $env:WEB_PORT }    else { 5173 }

$Root    = $PSScriptRoot
$Logs    = Join-Path $Root '.run-logs'
$ApiDir  = Join-Path $Root 'hospital-hotline-assistant-api'
$WebDir  = Join-Path $Root 'hospital-hotline-assistant-web'
$SpeechDir = Join-Path $Root 'local-speech'
$ApiEnv  = Join-Path $ApiDir '.env'
$WebEnv  = Join-Path $WebDir '.env'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$script:Started = @()

function Test-Url([string]$Url, [int]$TimeoutSec = 5) {
    # 2s was too tight and produced false negatives on a service that was up.
    try {
        Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing | Out-Null
        return $true
    } catch { return $false }
}

# Run a native command with a hard deadline. `ollama list` blocks indefinitely
# when the server is wedged, which hung the whole script; nothing here is
# important enough to wait forever for.
function Invoke-WithTimeout([scriptblock]$Script, [int]$TimeoutSec = 15) {
    $job = Start-Job -ScriptBlock $Script
    try {
        if (Wait-Job $job -Timeout $TimeoutSec) { return Receive-Job $job }
        return $null
    } finally { Remove-Job $job -Force -ErrorAction SilentlyContinue }
}

function Wait-For([string]$Url, [string]$Name, [int]$Seconds) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-Url $Url) { Write-Host "  [ok] $Name"; return $true }
        Start-Sleep -Seconds 1
    }
    Write-Host "  [!!] $Name did not come up" -ForegroundColor Red
    return $false
}

# Rewrite a KEY=value line in place, leaving the rest of the file untouched.
function Set-EnvValue([string]$File, [string]$Key, [string]$Value) {
    if (-not (Test-Path $File)) { return }
    $lines = Get-Content $File
    if ($lines -match "^$([regex]::Escape($Key))=") {
        $lines = $lines -replace "^$([regex]::Escape($Key))=.*", "$Key=$Value"
    } else {
        $lines += "$Key=$Value"
    }
    Set-Content -Path $File -Value $lines -Encoding utf8
}

function Sync-Env {
    if (-not (Test-Path $ApiEnv)) {
        Write-Host "  [!!] $ApiEnv missing — copy .env.example first" -ForegroundColor Red
        return
    }
    $base = "http://localhost:$SpeechPort/v1"
    # AI_MODE is the switch that actually moves the providers on-prem. Setting
    # only the URLs leaves the providers on vertexai/google, which silently
    # sends patient audio to the cloud — the one thing this stack exists to
    # prevent. See config.py::_apply_ai_mode.
    Set-EnvValue $ApiEnv 'AI_MODE' 'local'
    Set-EnvValue $ApiEnv 'STT_BASE_URL' $base
    Set-EnvValue $ApiEnv 'TTS_BASE_URL' $base
    Set-EnvValue $ApiEnv 'SCREENING_OPENAI_BASE_URL' $base
    Set-EnvValue $WebEnv 'VITE_API_BASE_URL' "http://localhost:$ApiPort"

    if ((Get-Content $ApiEnv -Raw) -notmatch "localhost:$WebPort") {
        Write-Host "  [!!] add http://localhost:$WebPort to CORS_ORIGINS in $ApiEnv" -ForegroundColor Yellow
    }
}

# The configured model must actually exist in Ollama, or every turn 404s with
# a message that never reaches the kiosk. Cheap to check, expensive to debug.
function Test-Model {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { return }
    $want = $null
    if (Test-Path $ApiEnv) {
        $line = Select-String -Path $ApiEnv -Pattern '^SCREENING_MODEL_NAME=(.+)$' |
                Select-Object -First 1
        if ($line) { $want = $line.Matches[0].Groups[1].Value.Trim() }
    }
    if (-not $want) { return }
    $raw = Invoke-WithTimeout { ollama list 2>$null } 20
    if ($null -eq $raw) {
        Write-Host '  [!!] `ollama list` timed out — skipping model check' -ForegroundColor Yellow
        return
    }
    $installed = @($raw | Select-Object -Skip 1 |
                   ForEach-Object { ($_ -split '\s+')[0] } |
                   Where-Object { $_ })
    # `ollama list` always prints an explicit tag; .env usually omits it, and
    # a bare name means :latest. Compare both ways or this warns on a match.
    $norm = { param($n) if ($n -match ':') { $n } else { "${n}:latest" } }
    $installedNorm = $installed | ForEach-Object { & $norm $_ }
    if ($installedNorm -notcontains (& $norm $want)) {
        Write-Host "  [!!] SCREENING_MODEL_NAME='$want' is not in ollama list" -ForegroundColor Yellow
        Write-Host "       installed: $($installed -join ', ')" -ForegroundColor Yellow
        Write-Host "       fix: ollama pull $want   (or point .env at one above)" -ForegroundColor Yellow
    }
}

function Show-Check {
    Write-Host 'Health:'
    $checks = @(
        @{ Url = "http://localhost:$OllamaPort/api/tags"; Name = "ollama   :$OllamaPort" },
        @{ Url = "http://localhost:$SpeechPort/health";   Name = "speech   :$SpeechPort" },
        @{ Url = "http://localhost:$ApiPort/health";      Name = "backend  :$ApiPort" },
        @{ Url = "http://localhost:$WebPort/";            Name = "kiosk    :$WebPort" }
    )
    foreach ($c in $checks) {
        if (Test-Url $c.Url) { Write-Host "  [ok] $($c.Name)" }
        else { Write-Host "  [--] $($c.Name)" -ForegroundColor DarkGray }
    }
    # Docker Desktop may be absent or simply not on PATH in this shell; with
    # ErrorActionPreference=Stop an unguarded call aborts the whole health check.
    $dockerUp = $false
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            $dockerUp = [bool](docker ps --filter name=hospital_hotline_db --format '{{.Names}}' 2>$null)
        } catch { $dockerUp = $false }
    }
    if ($dockerUp) { Write-Host '  [ok] postgres :5432' }
    else { Write-Host '  [--] postgres :5432' -ForegroundColor DarkGray }
    Test-Model
}

# Launch detached, logging to a file, and remember it so Stop-All can kill it.
function Start-Service-Bg([string]$Name, [string]$Exe, [string[]]$ArgList, [string]$Cwd) {
    $log = Join-Path $Logs "$Name.log"
    $p = Start-Process -FilePath $Exe -ArgumentList $ArgList -WorkingDirectory $Cwd `
         -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
         -WindowStyle Hidden -PassThru
    $script:Started += $p
    return $p
}

function Stop-All {
    if (-not $script:Started) { return }
    Write-Host "`nstopping..."
    foreach ($p in $script:Started) {
        try { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } } catch {}
    }
}

function Start-Speech {
    if (Test-Url "http://localhost:$SpeechPort/health") {
        Write-Host '  [ok] local-speech (already running)'
        return
    }
    # Prefer the console script, but fall back to `python -m uvicorn`: the .exe
    # shim only appears once the full requirements set is installed, while the
    # module works as soon as uvicorn itself is there.
    $uvicorn = Join-Path $SpeechDir 'venv\Scripts\uvicorn.exe'
    $python  = Join-Path $SpeechDir 'venv\Scripts\python.exe'
    if (Test-Path $uvicorn) {
        $exe = $uvicorn
        $argList = @('server:app', '--host', '0.0.0.0', '--port', "$SpeechPort")
    } elseif (Test-Path $python) {
        $exe = $python
        $argList = @('-m', 'uvicorn', 'server:app', '--host', '0.0.0.0', '--port', "$SpeechPort")
    } else {
        Write-Host "  [!!] no venv at $SpeechDir\venv — create it:" -ForegroundColor Red
        Write-Host "       py -m venv $SpeechDir\venv" -ForegroundColor Red
        Write-Host "       $SpeechDir\venv\Scripts\pip install -r $SpeechDir\requirements.txt" -ForegroundColor Red
        return
    }
    Start-Service-Bg 'speech' $exe $argList $SpeechDir | Out-Null
    # First run downloads whisper + MMS weights, so allow well past a normal boot.
    Wait-For "http://localhost:$SpeechPort/health" 'local-speech' 180 | Out-Null
}

if ($Mode -eq 'check') { Show-Check; return }

try {
    if ($Mode -eq 'ai') {
        # Pick a REACHABLE address. Excluding loopback and APIPA is not enough:
        # Hyper-V/WSL vEthernet adapters are "Up" with a routable-looking
        # address that no other machine can reach, and they sort first. Same
        # trap as the Docker bridge in docs/local-ai-connecting.md.
        $cands = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            ForEach-Object {
                $ad = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
                [pscustomobject]@{
                    IP      = $_.IPAddress
                    Alias   = $_.InterfaceAlias
                    Up      = ($ad.Status -eq 'Up')
                    Virtual = ($_.InterfaceAlias -match 'vEthernet|WSL|Loopback|Hyper-V' -or
                               $ad.InterfaceDescription -match 'Hyper-V|Virtual')
                    Vpn     = ($_.InterfaceAlias -match 'Tailscale|VPN|WireGuard')
                }
            }
        $ip = ($cands | Where-Object { $_.Up -and -not $_.Virtual -and -not $_.Vpn } |
               Select-Object -First 1).IP
        if (-not $ip) { $ip = ($cands | Where-Object { $_.Up -and -not $_.Virtual } | Select-Object -First 1).IP }
        Write-Host "AI node — reachable at $ip (speech :$SpeechPort, llm :$OllamaPort)"
        $others = $cands | Where-Object { $_.Up -and $_.IP -ne $ip }
        if ($others) {
            Write-Host '  other addresses on this host:'
            foreach ($o in $others) {
                $tag = if ($o.Virtual) { ' — virtual, NOT reachable from other machines' }
                       elseif ($o.Vpn) { ' — VPN; use when the app node is on another network' }
                       else { '' }
                Write-Host "    $($o.IP)  ($($o.Alias))$tag"
            }
        }

        # Ollama deliberately stays on localhost: local-speech proxies
        # /v1/chat/completions to it, so only :SpeechPort leaves the machine and
        # there is no unauthenticated LLM endpoint on the hospital LAN.
        if (Test-Url "http://localhost:$OllamaPort/api/tags") {
            Write-Host "  [ok] ollama (private on localhost, proxied via :$SpeechPort)"
        } else {
            Write-Host '  [!!] ollama is not running — start it with: ollama serve' -ForegroundColor Red
        }
        Start-Speech
        Test-Model

        Write-Host "`nOn the backend machine, set in hospital-hotline-assistant-api\.env:"
        Write-Host "  AI_MODE=local"
        Write-Host "  SCREENING_OPENAI_BASE_URL=http://${ip}:$SpeechPort/v1"
        Write-Host "  STT_BASE_URL=http://${ip}:$SpeechPort/v1"
        Write-Host "  TTS_BASE_URL=http://${ip}:$SpeechPort/v1"
        if ($script:Started) {
            Write-Host "`nCtrl-C to stop. Logs: $Logs"
            Get-Content (Join-Path $Logs 'speech.log') -Wait -Tail 20
        }
        return
    }

    Write-Host "Ports: speech=$SpeechPort ollama=$OllamaPort api=$ApiPort web=$WebPort"
    Sync-Env

    Write-Host '[1/5] databases'
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            docker compose -f (Join-Path $Root 'docker-compose.yml') up -d 2>&1 | Out-Null
            Write-Host '  [ok] postgres + his-mock'
        } catch {
            Write-Host '  [!!] docker compose failed — is Docker Desktop running?' -ForegroundColor Red
        }
    } else {
        Write-Host '  [!!] docker not on PATH — start Docker Desktop first' -ForegroundColor Red
    }

    Write-Host '[2/5] ollama'
    if (-not (Test-Url "http://localhost:$OllamaPort/api/tags")) {
        Start-Service-Bg 'ollama' 'ollama' @('serve') $Root | Out-Null
        Wait-For "http://localhost:$OllamaPort/api/tags" 'ollama' 30 | Out-Null
    } else { Write-Host '  [ok] ollama (already running)' }

    Write-Host '[3/5] local-speech'
    Start-Speech

    Write-Host '[4/5] backend'
    Start-Service-Bg 'api' 'uv' @('run', 'uvicorn', 'app.main:app', '--port', "$ApiPort", '--reload') $ApiDir | Out-Null
    Wait-For "http://localhost:$ApiPort/health" 'backend' 90 | Out-Null

    Write-Host '[5/5] kiosk'
    Start-Service-Bg 'web' 'npm.cmd' @('run', 'dev', '--', '--port', "$WebPort") $WebDir | Out-Null
    Wait-For "http://localhost:$WebPort/" 'kiosk' 60 | Out-Null

    Write-Host ''
    Show-Check
    Write-Host "`nKiosk:  http://localhost:$WebPort/kiosk"
    Write-Host "Logs:   $Logs\{ollama,speech,api,web}.log"
    Write-Host 'Ctrl-C to stop everything started here.'
    Get-Content (Join-Path $Logs 'api.log') -Wait -Tail 20
}
finally {
    Stop-All
}
