<#
.SYNOPSIS
  Démarre Docker Desktop s'il ne répond pas, puis attend son moteur.

.DESCRIPTION
  Appelé par TradingOS.bat avant les modes Full et Infrastructure, jamais avant Status, Stop, Doctor ni MT5.
  Décision d'Exhorte du 2026-11-22 : ADR 0038, A11 « Docker Desktop éteint », dans son sens « le lancer » (avant : message seulement).

  Il ne fait qu'une chose : si « docker info » ne répond pas, lancer l'exécutable de Docker Desktop (une seule fois, et jamais si son processus tourne
  déjà), puis attendre le moteur, au plus -TimeoutSeconds. Il ne ferme rien, ne touche à aucun conteneur, ne lit et n'écrit aucun fichier, n'ouvre
  aucun secret. Un chemin donné avec -DesktopPath n'est jamais remplacé par une supposition.

  Code de sortie : 0 le moteur répond · 1 il ne répond pas (exécutable introuvable, ou délai dépassé). Le .bat continue alors : c'est le lanceur qui
  dit « Docker Desktop ne répond pas ».

.PARAMETER TimeoutSeconds
  Attente maximale du moteur après le lancement (180 s par défaut : un premier démarrage de Windows peut être long).

.PARAMETER PollSeconds
  Intervalle entre deux questions « docker info ».

.PARAMETER DockerCommand
  La commande docker (les tests s'en servent).

.PARAMETER DesktopPath
  L'exécutable de Docker Desktop. Absent : les deux emplacements d'installation habituels (profil de l'utilisateur, puis Program Files).

.PARAMETER ProcessName
  Le nom du processus de Docker Desktop, pour ne jamais le lancer deux fois.
#>
[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 180,
    [int]$PollSeconds = 3,
    [string]$DockerCommand = 'docker',
    [string]$DesktopPath,
    [string]$ProcessName = 'Docker Desktop'
)

$ErrorActionPreference = 'Continue'

# Les messages sont en UTF-8 : sans cela, Windows PowerShell 5.1 les décoderait avec la page de code de la console.
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Test-Engine {
    try {
        & $DockerCommand info *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch { return $false }
}

function Find-Desktop {
    if ($DesktopPath) {
        if (Test-Path -LiteralPath $DesktopPath -PathType Leaf) { return $DesktopPath }
        return $null
    }
    $candidates = @()
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe') }
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe') }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

if (Test-Engine) { exit 0 }

$already = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
if ($already) {
    Write-Host "Docker Desktop est lancé mais son moteur ne répond pas encore : attente, au plus $TimeoutSeconds s."
}
else {
    $exe = Find-Desktop
    if (-not $exe) {
        $named = if ($DesktopPath) { $DesktopPath } else { 'Docker Desktop.exe' }
        [Console]::Error.WriteLine("Docker Desktop est introuvable ($named) : le lanceur dira que Docker ne répond pas.")
        exit 1
    }
    Write-Host "Docker Desktop ne répond pas : démarrage, attente du moteur au plus $TimeoutSeconds s."
    Start-Process -FilePath $exe
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $PollSeconds
    if (Test-Engine) {
        Write-Host 'Docker Desktop est prêt.'
        exit 0
    }
}
[Console]::Error.WriteLine("Docker Desktop n'a pas répondu en $TimeoutSeconds s : le lanceur dira que Docker ne répond pas.")
exit 1
