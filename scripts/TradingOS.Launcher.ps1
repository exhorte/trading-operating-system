<#
.SYNOPSIS
  Point d'entrée de Trading OS : choisit un mode et appelle le lanceur Python.

.DESCRIPTION
  Ce script ne fait que trouver le dépôt, fixer le dossier courant à 04_code\python (le cœur ne s'importe que de là : audit D2, ADR 0038)
  et appeler « python -m trading_os launcher ... ». Toute la logique est dans le lanceur Python (ADR 0038, ADR 0039) : ici, aucun
  processus n'est arrêté, aucun fichier n'est lu ni écrit, aucun conteneur n'est touché, MetaTrader n'est pas touché.

  Le code de sortie est celui du lanceur : 0 rien d'anormal · 1 un problème, un refus ou un échec · 2 la machine n'a pas pu être observée.

  Modes :
    Full            (défaut) « launcher start » (base, schéma, cœur, cockpit), puis « launcher mt5 plan » si le démarrage a réussi.
                    Avec -Json, seule l'infrastructure est rapportée sur la sortie (une note va sur la sortie d'erreur).
    Infrastructure  « launcher start » : démarre ce qui manque, laisse en paix ce qui est sain.
    MT5             « launcher mt5 plan » : détecte les terminaux MetaTrader 5, dit ce qui est enregistré et ce que la préparation
                    ferait ensuite. Lecture seule. Déploiement, preset et lancement ne sont pas encore construits (ADR 0039, I4 à I7).
    Status          « launcher status » : ce qui tourne, à qui c'est. Lecture seule.
    Stop            « launcher stop » : arrête seulement ce que le lanceur a démarré. Jamais MetaTrader, jamais une position.
    Doctor          « launcher doctor » : explique ce qui ne va pas et quoi faire. Lecture seule, ne répare rien.

  Ce script n'arme rien, ne rattache aucun compte, n'envoie aucun ordre.

.PARAMETER Mode
  Full (défaut), Infrastructure, MT5, Status, Stop ou Doctor.

.PARAMETER Apply
  Réservé aux étapes de MetaTrader 5 qui écriront ou lanceront quelque chose (I4 à I7) : sans effet tant qu'elles ne sont pas construites.

.PARAMETER DryRun
  Mode Stop seulement : dit ce qui serait arrêté, n'arrête rien.

.PARAMETER IncludeDatabase
  Mode Stop seulement : arrête aussi le conteneur de la base, même si le lanceur ne l'a pas démarré.

.PARAMETER Json
  Sortie JSON du lanceur (modes Status, Stop, Infrastructure, Full, Doctor) ; aucun autre texte n'est écrit.

.PARAMETER PythonPath
  Un autre interpréteur Python que celui de python\.venv (les tests s'en servent).

.EXAMPLE
  TradingOS.bat Status
.EXAMPLE
  TradingOS.bat Stop -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('Full', 'Infrastructure', 'MT5', 'Status', 'Stop', 'Doctor')]
    [string]$Mode = 'Full',
    [switch]$Apply,
    [switch]$DryRun,
    [switch]$IncludeDatabase,
    [switch]$Json,
    [string]$PythonPath
)

# Les commandes natives disent leur échec par leur code de sortie, relu plus bas.
$ErrorActionPreference = 'Continue'

# Les rapports du lanceur sont en UTF-8 : sans cela, Windows PowerShell 5.1 les décoderait avec la page de code de la console.
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$root = Split-Path -Parent $PSScriptRoot
$pythonDir = Join-Path $root 'python'
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $pythonDir '.venv\Scripts\python.exe'
}

function Write-Note([string]$Text) {
    # Rien d'autre que le JSON du lanceur sur la sortie quand -Json est demandé.
    if (-not $Json) { Write-Host $Text }
}

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    [Console]::Error.WriteLine("Le Python du coeur est introuvable : $PythonPath")
    [Console]::Error.WriteLine('Depuis 04_code\python : py -3.14 -m venv .venv puis .venv\Scripts\python.exe -m pip install -e ".[dev]"')
    exit 2
}

$script:exitCode = 0

function Invoke-Launcher([string[]]$Words) {
    Push-Location -LiteralPath $pythonDir
    try {
        & $PythonPath -m trading_os launcher @Words
        $script:exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

if ($DryRun -and $Mode -ne 'Stop') { Write-Note "-DryRun ignoré hors du mode Stop." }
if ($IncludeDatabase -and $Mode -ne 'Stop') { Write-Note "-IncludeDatabase ignoré hors du mode Stop." }
if ($Apply) {
    if ($Mode -in @('Full', 'MT5')) {
        Write-Note "-Apply : sans effet pour l'instant -- le déploiement, le preset et le lancement de MetaTrader 5 ne sont pas encore construits (incréments I4 à I7)."
    }
    else { Write-Note "-Apply ignoré hors des modes Full et MT5." }
}

switch ($Mode) {
    'MT5' { $words = @('mt5', 'plan') }
    'Status' { $words = @('status') }
    'Doctor' { $words = @('doctor') }
    'Infrastructure' { $words = @('start') }
    'Full' { $words = @('start') }
    'Stop' {
        $words = @('stop')
        if ($DryRun) { $words += '--dry-run' }
        if ($IncludeDatabase) { $words += '--include-database' }
    }
}
if ($Json) { $words += '--json' }

Invoke-Launcher $words

if ($Mode -eq 'Full' -and $script:exitCode -eq 0) {
    if ($Json) {
        # stdout stays the infrastructure's JSON alone: the MetaTrader part has its own mode
        [Console]::Error.WriteLine('-Json : seule l''infrastructure est rapportée ; le mode MT5 -Json donne la préparation de MetaTrader 5.')
    }
    else {
        Write-Host ''
        Invoke-Launcher @('mt5', 'plan')
    }
}
exit $script:exitCode
