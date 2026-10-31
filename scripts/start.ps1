<#
.SYNOPSIS
  Démarre le Trading OS : la base, le cœur Python, le cockpit.

.DESCRIPTION
  Depuis la migration Python-native (ADR 0016) il n'y a plus de backend .NET, d'observateur ni d'exportateur :
  le cœur Python lit MT5 lui-même (un processus fils en lecture seule par terminal), sert l'API et le WebSocket
  du cockpit (127.0.0.1:8000) et le lien de l'agent EA (127.0.0.1:9765).

  Dans l'ordre :
    0. jetons locaux : TRADINGOS_COCKPIT_TOKEN et TRADINGOS_AGENT_TOKEN, écrits une fois dans le .env gitignoré
       s'ils manquent, avec DATABASE_URL de la base locale — jamais affichés ;
    1. base TimescaleDB (conteneur tradingos-timescaledb, port 5433) ;
    2. schéma : python -m trading_os db migrate (migrations additives seulement : un script destructeur ne se
       lance jamais d'ici, il se tape à la main — `db manual <nom> --confirm <nom>`) ;
    3. jeton de l'agent copié dans MQL5\Files de chaque terminal MT5 ouvert ;
    4. cœur Python (fenêtre dédiée, ses journaux y restent) ;
    5. cockpit (npm run dev, port 3000), s'il ne tourne pas déjà.

  Ce que ce script ne fait jamais : se connecter à un broker, demander ou stocker un identifiant, ouvrir MT5 à ta
  place, attacher l'agent EA, relever le plafond de mode (TRADING_MODE reste OBSERVE sauf si tu l'écris dans .env),
  armer quoi que ce soit, ni arrêter un conteneur qui n'est pas à lui. Le compte se rattache dans le cockpit
  (Settings) ; MT5 garde le mot de passe.

.PARAMETER Simulated
  Démarre le cœur sans terminal (MT5_ENABLED=false pour ce processus seulement) : un terminal simulé de
  démonstration — deux positions ouvertes, un petit historique, des cotes qui bougent. Pour regarder le cockpit.

.PARAMETER Plan
  N'exécute rien et n'écrit rien : dit ce que chaque étape ferait.

.PARAMETER TerminalDataPath
  Dossier de données d'un terminal MT5 en plus de ceux détectés (MT5 : Fichier → Ouvrir le dossier de données).

.EXAMPLE
  pwsh -File scripts\start.ps1
.EXAMPLE
  pwsh -File scripts\start.ps1 -Simulated
.EXAMPLE
  pwsh -File scripts\start.ps1 -Plan
#>
[CmdletBinding()]
param(
    [switch]$Simulated,
    [switch]$Plan,
    [string]$TerminalDataPath
)

# Native commands (docker, python, npm) report through exit codes, checked one by one below; "Stop" would turn their
# progress output on stderr into terminating errors under Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$core = "http://127.0.0.1:8000"
$containerName = "tradingos-timescaledb"
$python = Join-Path $root "python\.venv\Scripts\python.exe"
$envFile = Join-Path $root ".env"
# La base locale du dépôt (docker-compose.yml) : mot de passe de développement, port 5433 sur la boucle locale seulement.
$defaultDatabaseUrl = "postgresql://tradingos:tradingos_dev@127.0.0.1:5433/tradingos"

function Step([string]$text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok([string]$text) { Write-Host "    ok  $text" -ForegroundColor Green }
function Note([string]$text) { Write-Host "    ..  $text" -ForegroundColor Gray }
function Warn([string]$text) { Write-Host "    !!  $text" -ForegroundColor Yellow }
function Would([string]$text) { Write-Host "    ->  $text" -ForegroundColor DarkCyan }
function Fail([string]$text) {
    Write-Host "    XX  $text" -ForegroundColor Red
    exit 1
}

function Start-Window([string]$title, [string]$command) {
    # Une fenêtre par processus long : le trader voit ses journaux, et il survit à ce script.
    $full = "`$Host.UI.RawUI.WindowTitle = '$title'; $command"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $root -ArgumentList @("-NoExit", "-Command", $full) | Out-Null
}

function Read-EnvValue([string]$path, [string]$name) {
    # La dernière ligne « NOM=valeur » gagne, comme dotenv. Jamais affichée.
    if (-not (Test-Path $path)) { return $null }
    $value = $null
    foreach ($line in [System.IO.File]::ReadAllLines($path)) {
        if ($line -match "^[ \t]*$([regex]::Escape($name))[ \t]*=[ \t]*(\S+)[ \t]*$") { $value = $Matches[1] }
    }
    return $value
}

function Add-EnvLine([string]$path, [string]$name, [string]$value) {
    $content = if (Test-Path $path) { [System.IO.File]::ReadAllText($path) } else { "" }
    $separator = if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) { [Environment]::NewLine } else { "" }
    [System.IO.File]::AppendAllText($path, "$separator$name=$value" + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
}

function Test-EnvHas([string]$path, [string]$name) {
    $content = if (Test-Path $path) { [System.IO.File]::ReadAllText($path) } else { "" }
    # Des blancs horizontaux seulement, jamais \s : une ligne « NOM= » vide ne doit pas emprunter la valeur de la suivante.
    return [bool]($content -match "(?m)^[ \t]*$([regex]::Escape($name))[ \t]*=[ \t]*\S")
}

function New-LocalToken {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    # base64url : aucun caractère que dotenv ou un en-tête HTTP interpréterait.
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-Mt5DataFolders {
    # Les dossiers de données des terminaux MT5 ouverts : le dossier d'AppData dont origin.txt nomme le dossier
    # d'installation du terminal ; pour un terminal lancé en /portable, le dossier d'installation lui-même.
    $found = @()
    $terminals = @(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path })
    foreach ($terminal in $terminals) {
        $install = Split-Path -Parent $terminal.Path
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($terminal.Id)" -ErrorAction SilentlyContinue
        if ($cim -and $cim.CommandLine -match "(?i)/portable") {
            $found += $install
            continue
        }
        $base = Join-Path $env:APPDATA "MetaQuotes\Terminal"
        if (-not (Test-Path $base)) { continue }
        foreach ($dir in Get-ChildItem $base -Directory -ErrorAction SilentlyContinue) {
            $originFile = Join-Path $dir.FullName "origin.txt"
            if (-not (Test-Path $originFile)) { continue }
            $origin = (Get-Content $originFile -Encoding Unicode -TotalCount 1)
            if ($origin -and ($origin.Trim().TrimEnd('\') -ieq $install.TrimEnd('\'))) { $found += $dir.FullName }
        }
    }
    return @($found | Select-Object -Unique)
}

# --- 0. Jetons locaux ---------------------------------------------------------
# Secrets partagés entre les processus du Trading OS : le cockpit présente le premier au cœur (REST et WebSocket),
# l'agent MQL5 le second (copié à l'étape 3 dans MQL5\Files du terminal). Le cœur et `next dev` lisent .env eux-mêmes.
Step "Jetons locaux et base (.env)"
$created = @()
foreach ($tokenName in @("TRADINGOS_COCKPIT_TOKEN", "TRADINGOS_AGENT_TOKEN")) {
    if (-not (Test-EnvHas $envFile $tokenName)) {
        if ($Plan) { Would "écrirait $tokenName dans .env (valeur aléatoire, jamais affichée)" }
        else { Add-EnvLine $envFile $tokenName (New-LocalToken) }
        $created += $tokenName
    }
}
if (-not (Test-EnvHas $envFile "DATABASE_URL")) {
    if ($Plan) { Would "écrirait DATABASE_URL dans .env (la base locale du dépôt, 127.0.0.1:5433)" }
    else { Add-EnvLine $envFile "DATABASE_URL" $defaultDatabaseUrl }
    $created += "DATABASE_URL"
}
if ($created) {
    if (-not $Plan) { Ok ("écrit dans .env : " + ($created -join ", ")) }
    Note "un cockpit déjà ouvert relit .env seul ; un cœur déjà lancé doit être relancé (étape 4 le dit)"
} else {
    Ok "jetons et DATABASE_URL présents dans .env"
}
if (-not (Test-EnvHas $envFile "FRED_API_KEY")) {
    Note "FRED_API_KEY absent de .env : sans calendrier, la porte « actualités » reste fermée (échec fermé) — voir .env.example"
}

# --- 1. Base ------------------------------------------------------------------
Step "Base TimescaleDB (port 5433)"
$dockerOk = $false
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    if ($Plan) { Warn "docker introuvable — un vrai lancement s'arrêterait ici." } else { Fail "docker introuvable — Docker Desktop est-il installé et démarré ?" }
} else {
    docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
    elseif ($Plan) { Warn "Docker Desktop ne répond pas — un vrai lancement s'arrêterait ici." }
    else { Fail "Docker Desktop ne répond pas — démarre-le puis relance ce script." }
}

$holders = @()
$exists = @()
if ($dockerOk) {
    $holders = @(docker ps --filter "publish=5433" --format "{{.Names}}") | Where-Object { $_ -and $_ -ne $containerName }
    if ($holders) {
        Fail ("Le port 5433 est pris par « " + ($holders -join ", ") + " » (un autre projet). " +
            "Ce script ne touche pas aux conteneurs des autres : arrête-le toi-même (docker stop $($holders[0])), puis relance.")
    }
    $exists = @(docker ps -a --filter "name=^/$containerName$" --format "{{.Names}}")
}
if (-not $dockerOk) {
    # rien à dire de plus : le plan ci-dessus l'a déjà dit
} elseif ($Plan) {
    if ($exists) { Would "démarrerait le conteneur $containerName (docker start) et attendrait qu'il soit « healthy »" }
    else { Would "créerait le conteneur depuis docker-compose.yml (docker compose up -d timescaledb)" }
} else {
    if ($exists) {
        docker start $containerName *> $null
        if ($LASTEXITCODE -ne 0) { Fail "Impossible de démarrer $containerName (docker start)." }
    } else {
        Push-Location $root
        docker compose up -d timescaledb *> $null
        $composeExit = $LASTEXITCODE
        Pop-Location
        if ($composeExit -ne 0) {
            Fail ("docker compose up -d timescaledb a échoué. Le volume des données est déclaré externe dans docker-compose.yml : " +
                "il doit déjà exister (docker volume ls) — ce script n'en crée jamais un vide à la place de tes données.")
        }
    }
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $health = docker inspect -f "{{.State.Health.Status}}" $containerName
        if ($health -eq "healthy") { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if ($health -ne "healthy") { Fail "$containerName n'est pas « healthy » après 90 s (état : $health)." }
    Ok "$containerName healthy"
}

# --- 2. Schéma ----------------------------------------------------------------
Step "Schéma de la base (migrations additives)"
$venvHelp = "L'environnement Python du cœur est absent ($python). Depuis 04_code\python : " +
    "py -3.14 -m venv .venv ; .venv\Scripts\python.exe -m pip install -e `".[dev]`""
if (-not (Test-Path $python)) {
    if ($Plan) { Warn $venvHelp } else { Fail $venvHelp }
}
if ($Plan) {
    Would "lancerait : python -m trading_os db migrate (n'applique que les migrations numérotées en attente)"
} else {
    Push-Location (Join-Path $root "python")
    & $python -m trading_os db migrate
    $migrateExit = $LASTEXITCODE
    Pop-Location
    if ($migrateExit -ne 0) { Fail "db migrate a échoué — le cœur ne démarre pas sur un schéma qu'il ne connaît pas." }
    Ok "schéma à jour"
}

# --- 3. Jeton de l'agent dans les terminaux MT5 -------------------------------
# L'agent lit son jeton dans MQL5\Files du terminal (jamais un input : un input atterrit dans le préréglage et les
# propriétés du graphique). Réécrit à chaque lancement : .env et le terminal ne divergent jamais.
Step "Jeton de l'agent EA dans les terminaux MT5"
$agentToken = Read-EnvValue $envFile "TRADINGOS_AGENT_TOKEN"
$folders = @(Get-Mt5DataFolders)
if ($TerminalDataPath) { $folders += $TerminalDataPath }
$folders = @($folders | Select-Object -Unique)
if (-not $folders) {
    Note "aucun terminal MT5 ouvert : rien à écrire. Ouvre MT5, connecte-toi au compte voulu (le mot de passe reste dans MT5), puis relance ce script — ou passe -TerminalDataPath."
} elseif ($Plan) {
    foreach ($folder in $folders) { Would "écrirait le jeton de l'agent dans $folder\MQL5\Files\tradingos_agent.token" }
} elseif (-not $agentToken) {
    Warn "TRADINGOS_AGENT_TOKEN absent de .env : jeton de l'agent non écrit."
} else {
    foreach ($folder in $folders) {
        $filesDir = Join-Path $folder "MQL5\Files"
        if (-not (Test-Path $filesDir)) { New-Item -ItemType Directory -Path $filesDir | Out-Null }
        [System.IO.File]::WriteAllText((Join-Path $filesDir "tradingos_agent.token"), $agentToken, [System.Text.Encoding]::ASCII)
        Ok "jeton écrit dans $filesDir (lu par l'agent à chaque connexion)"
    }
}

# --- 4. Cœur ------------------------------------------------------------------
Step "Cœur Python ($core)"
$health = $null
try { $health = Invoke-RestMethod -Uri "$core/api/system/health" -TimeoutSec 3 } catch { $health = $null }
if ($health) {
    Note "un cœur répond déjà sur $core — laissé tel quel (version $($health.version), démarré à $($health.startedAt))"
    if ($created -and -not $Plan) { Warn "des jetons viennent d'être écrits : arrête ce cœur (sa fenêtre) puis relance ce script, pour qu'il les lise." }
    if ($Simulated) { Warn "-Simulated est sans effet : ce cœur tournait déjà (arrête-le d'abord pour le relancer en mode simulé)." }
} else {
    if ($Simulated) { Note "mode simulé : MT5_ENABLED=false pour ce processus (aucun terminal, un terminal de démonstration en mémoire)" }
    if ($Plan) {
        Would "ouvrirait une fenêtre : python -m trading_os serve$(if ($Simulated) { ' (MT5_ENABLED=false)' })"
    } else {
        $prefix = if ($Simulated) { "`$env:MT5_ENABLED = 'false'; " } else { "" }
        Start-Window "Trading OS - coeur" "$prefix& '$python' -m trading_os serve"
        $deadline = (Get-Date).AddSeconds(60)
        do {
            Start-Sleep -Seconds 2
            try { $health = Invoke-RestMethod -Uri "$core/api/system/health" -TimeoutSec 3 } catch { $health = $null }
        } while (-not $health -and (Get-Date) -lt $deadline)
        if (-not $health) { Fail "Le cœur ne répond pas sur $core après 60 s — regarde sa fenêtre." }
        if (-not $health.database.up) { Fail "Le cœur est lancé mais sa base est injoignable : $($health.database.lastError)" }
        Ok "cœur en ligne, base ok (version $($health.version))"
    }
}

# --- 5. Cockpit ---------------------------------------------------------------
Step "Cockpit (http://127.0.0.1:3000)"
$listening = @(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)
if ($listening) {
    Note "quelque chose écoute déjà sur le port 3000 — laissé tel quel"
    if ($listening | Where-Object { $_.LocalAddress -in @("0.0.0.0", "::") }) {
        # Lancé avant que package.json ne passe -H 127.0.0.1.
        Warn "il écoute sur toutes les interfaces (réseau local compris) : arrête-le et relance ce script pour le lier à 127.0.0.1."
    }
} elseif ($Plan) {
    Would "ouvrirait une fenêtre : npm run dev (127.0.0.1:3000)"
} else {
    Start-Window "Trading OS - cockpit" "npm run dev"
    Ok "cockpit lancé"
}

# --- Bilan --------------------------------------------------------------------
Step "Bilan"
if ($Plan) {
    Note "plan seulement : rien n'a été exécuté ni écrit."
} else {
    try { $health = Invoke-RestMethod -Uri "$core/api/system/health" -TimeoutSec 3 } catch { $health = $null }
    if ($health -and $health.agentsConnected -gt 0) {
        Ok "agent EA connecté"
    } else {
        Note "aucun agent EA connecté (normal si MT5 est fermé ou si l'agent n'est pas attaché). Pour l'attacher :"
        Note "MT5 → Navigateur → Expert Advisors → TradingOsAgent, glisse-le sur UN graphique ; InpMagicNumber = un nombre propre à ce compte ;"
        Note "InpAllowedSymbolsCsv et InpMaxSpreadCsv selon tools\mt5-execution-agent\README.md (un symbole sans spread max refuse tout ordre)."
    }
}
Note "Cockpit : http://127.0.0.1:3000 — le compte se rattache dans Settings (« Enregistrer le compte »), puis Account."
