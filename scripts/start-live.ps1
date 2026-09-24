<#
.SYNOPSIS
  Démarre l'environnement réel du Trading OS pour le compte ouvert dans MT5.

.DESCRIPTION
  T12 incrément 2 — un compte à la fois (décision T12 n°1) : le cockpit suit
  le terminal MT5 que tu as ouvert et connecté, FTMO ou Exness.

  Dans l'ordre du runbook (« Ordre de démarrage complet ») :
    1. base TimescaleDB (conteneur tradingos-timescaledb, port 5433) ;
    2. backend .NET (conteneur tradingos-backend, port 5080) ;
    3. observer MT5 en lecture seule, sur le symbole que CE terminal liste
       (FTMO : XAUUSD, Exness : XAUUSDm — tools/mt5-observer/probe_terminal.py) ;
    4. cockpit (npm run dev, port 3000), s'il ne tourne pas déjà ;
    5. en option (-WithSetupPipeline) : exportateur + worker S01 (runbook §5).

  Ce que ce script ne fait jamais : se connecter à un broker, demander ou
  stocker un identifiant, ouvrir MT5 à ta place, attacher l'agent EA-05,
  ni arrêter un conteneur qui n'est pas à lui. La connexion au compte se fait
  dans MT5 ; l'agent s'attache à la main (Settings → « Connexion MT5 »).
  L'agent reste en mode observe : aucun ordre ne part de ce système (EA-07
  fermé).

.PARAMETER WithSetupPipeline
  Lance aussi l'exportateur de bougies et le worker de détection S01.

.PARAMETER Symbol
  Force le symbole de l'observer au lieu de le déduire du broker.

.EXAMPLE
  pwsh -File scripts\start-live.ps1
.EXAMPLE
  pwsh -File scripts\start-live.ps1 -WithSetupPipeline
#>
[CmdletBinding()]
param(
    [switch]$WithSetupPipeline,
    [string]$Symbol
)

# Native commands (docker, python) report through exit codes, checked one
# by one below; "Stop" would turn their progress output on stderr into
# terminating errors under Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backend = "http://localhost:5080"

function Step([string]$text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok([string]$text) { Write-Host "    ok  $text" -ForegroundColor Green }
function Note([string]$text) { Write-Host "    ..  $text" -ForegroundColor Gray }
function Warn([string]$text) { Write-Host "    !!  $text" -ForegroundColor Yellow }
function Fail([string]$text) {
    Write-Host "    XX  $text" -ForegroundColor Red
    exit 1
}

function Get-ProcessesByCommandLine([string]$pattern) {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like $pattern }
}

function Start-Window([string]$title, [string]$command) {
    # A window per long-running process: the trader sees its logs, and it
    # outlives this script. Stopped later by command line (runbook §5).
    $full = "`$Host.UI.RawUI.WindowTitle = '$title'; $command"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList @("-NoExit", "-Command", $full) | Out-Null
}

# --- 1. Base ------------------------------------------------------------------
Step "Base TimescaleDB (port 5433)"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "docker introuvable — Docker Desktop est-il installé et démarré ?"
}
docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop ne répond pas — démarre-le puis relance ce script." }

$holders = @(docker ps --filter "publish=5433" --format "{{.Names}}") | Where-Object { $_ -and $_ -ne "tradingos-timescaledb" }
if ($holders) {
    Fail ("Le port 5433 est pris par « " + ($holders -join ", ") + " » (un autre projet). " +
        "Ce script ne touche pas aux conteneurs des autres : arrête-le toi-même (docker stop $($holders[0])), puis relance.")
}
docker start tradingos-timescaledb *> $null
if ($LASTEXITCODE -ne 0) { Fail "Impossible de démarrer tradingos-timescaledb (docker start)." }
$deadline = (Get-Date).AddSeconds(90)
do {
    $health = docker inspect -f "{{.State.Health.Status}}" tradingos-timescaledb
    if ($health -eq "healthy") { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
if ($health -ne "healthy") { Fail "tradingos-timescaledb n'est pas « healthy » après 90 s (état : $health)." }
Ok "tradingos-timescaledb healthy"

# --- 2. Backend ---------------------------------------------------------------
Step "Backend ($backend)"
Push-Location $root
docker compose up -d --no-deps backend *> $null
$composeExit = $LASTEXITCODE
Pop-Location
if ($composeExit -ne 0) { Fail "docker compose up -d --no-deps backend a échoué (runbook §2)." }
$deadline = (Get-Date).AddSeconds(60)
$healthy = $null
do {
    try { $healthy = Invoke-RestMethod -Uri "$backend/health" -TimeoutSec 3 } catch { $healthy = $null }
    if ($healthy -and $healthy.db -eq "ok") { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
if (-not $healthy) { Fail "Le backend ne répond pas sur $backend/health après 60 s — docker logs tradingos-backend." }
if ($healthy.db -ne "ok") { Fail "Backend démarré mais base injoignable : $($healthy.dbError)" }
Ok "backend en ligne, base ok"

# --- 3. Terminal MT5 et observer ---------------------------------------------
Step "Terminal MT5"
if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
    Fail ("MT5 n'est pas ouvert. Ouvre-le, connecte-toi au compte voulu " +
        "(Fichier → Connexion à un compte de trading), puis relance ce script. " +
        "Le mot de passe reste dans MT5 : ce script ne le demande jamais.")
}
Push-Location $root
$probeOutput = python tools/mt5-observer/probe_terminal.py
$probeExit = $LASTEXITCODE
Pop-Location
try { $probe = $probeOutput | ConvertFrom-Json } catch { $probe = $null }
if ($probeExit -ne 0 -or -not $probe -or $probe.error) {
    $reason = if ($probe -and $probe.error) { $probe.error } else { "$probeOutput" }
    Fail "Le terminal ne répond pas à la sonde : $reason"
}
$firmLabel = switch ($probe.firm) { "ftmo" { "FTMO" } "exness" { "Exness" } default { "broker non reconnu" } }
Ok "compte $($probe.login) — « $($probe.company) » ($($probe.server), $($probe.tradeMode), $($probe.currency)) → $firmLabel"
if ($probe.tradeMode -eq "real") {
    Warn "Compte RÉEL. Le cockpit l'observe ; l'agent EA-05 reste en mode observe, aucun ordre ne part d'ici."
}
if (-not $probe.firm) {
    Warn "Ni « ftmo » ni « exness » dans le nom du broker : règles par défaut. Ajuste la reconnaissance dans Settings si c'est l'un de tes comptes."
}

$observerSymbol = if ($Symbol) { $Symbol } else { $probe.observerSymbol }
if (-not $observerSymbol) {
    Fail ("Aucun symbole d'or attendu dans ce terminal (disponibles : " +
        (($probe.goldSymbols.PSObject.Properties | Where-Object { $_.Value } | ForEach-Object { $_.Name }) -join ", ") +
        "). Ajoute-le au Market Watch, ou force-le avec -Symbol.")
}

Step "Observer MT5 (lecture seule, --symbol $observerSymbol)"
$running = Get-ProcessesByCommandLine "*mt5_observer.py*"
if ($running) {
    # Switching accounts needs a fresh hello (broker, symbol): restart, never reuse.
    Note "un observer tournait déjà — arrêté pour repartir sur le compte ouvert"
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
Start-Window "Trading OS - observer $observerSymbol" "python tools/mt5-observer/mt5_observer.py --symbol $observerSymbol"

# The backend reconnects to the observer every 3 s; its account-settings
# guard is the one place that says whether a live account is attached.
$deadline = (Get-Date).AddSeconds(45)
$attached = $false
do {
    Start-Sleep -Seconds 3
    try {
        $ledger = Invoke-RestMethod -Uri "$backend/api/account-settings" -TimeoutSec 3
        $attached = -not ($ledger.guard.reasons | Where-Object { $_.code -eq "no_live_account" })
    } catch { $attached = $false }
} while (-not $attached -and (Get-Date) -lt $deadline)
if ($attached) {
    Ok "le backend reçoit le compte $($probe.login)"
} else {
    Warn "le backend ne voit pas encore l'observer après 45 s — regarde sa fenêtre (symbol not found ? MT5 fermé ?)."
}

# --- 4. Cockpit ---------------------------------------------------------------
Step "Cockpit (http://localhost:3000)"
if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) {
    Note "quelque chose écoute déjà sur le port 3000 — laissé tel quel"
} else {
    # Next 16 refuses a second `next dev` in the same folder: if the mock
    # preview (3001) is running, this window says so and stops.
    Start-Window "Trading OS - cockpit" "npm run dev"
    Ok "cockpit lancé — .env.local doit contenir NEXT_PUBLIC_REALTIME_SOURCE=backend"
}

# --- 5. Pipeline S01 (optionnel) ---------------------------------------------
if ($WithSetupPipeline) {
    Step "Pipeline S01 (exportateur + worker, runbook §5)"
    if (Get-ProcessesByCommandLine "*export_m1_candles*") {
        Note "exportateur déjà en route — une seule instance, laissé tel quel"
    } else {
        Start-Window "Trading OS - exportateur M1" "python tools/mt5-observer/export_m1_candles.py --symbols EURUSD GBPUSD --out-dir tools/mt5-observer"
        Ok "exportateur lancé (--out-dir tools/mt5-observer, le dossier que lit le worker)"
    }
    if (Get-ProcessesByCommandLine "*run-setup-detection*") {
        Note "worker déjà en route — une seule instance, laissé tel quel"
    } else {
        # The account id comes from the terminal at run time — never written
        # into the repository (.claude/CLAUDE.md).
        Start-Window "Trading OS - worker S01" "`$env:TRADINGOS_ACCOUNT_ID = '$($probe.login)'; npx tsx scripts/run-setup-detection.ts"
        Ok "worker lancé pour le compte $($probe.login)"
    }
}

# --- Bilan --------------------------------------------------------------------
Step "Bilan"
try { $healthy = Invoke-RestMethod -Uri "$backend/health" -TimeoutSec 3 } catch { $healthy = $null }
if ($healthy -and $healthy.agentConnected) {
    Ok "agent EA-05 connecté (mode observe)"
} else {
    $magic = switch ($probe.firm) { "ftmo" { "2001" } "exness" { "1001" } default { "un nombre propre à ce compte" } }
    $allowed = switch ($probe.firm) { "ftmo" { "EURUSD,GBPUSD" } default { "EURUSDm,GBPUSDm" } }
    Warn "agent EA-05 non connecté. Dans MT5 : Navigateur → Expert Advisors → TradingOsAgent, glisse-le sur un graphique, puis :"
    Note "InpAccountId = $($probe.login)   (à saisir toi-même dans MT5)"
    Note "InpMagicNumber = $magic   (unique par compte — jamais celui de l'autre)"
    Note "InpAllowedSymbolsCsv = $allowed"
    Note "Relance ce script ou regarde Account : la ligne « Agent d'exécution EA-05 » passe à Connecté."
}
Note "Account : http://localhost:3000/account — Settings : http://localhost:3000/settings"
