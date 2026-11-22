@echo off
rem ---------------------------------------------------------------------------
rem  Trading OS - point d'entree. Double-clic, ou : TradingOS.bat [Mode] [options]
rem  Modes : Full (defaut) | Infrastructure | MT5 | Status | Stop | Doctor
rem  Options : -DryRun -IncludeDatabase (Stop) -Apply -Json -PythonPath <python.exe>
rem
rem  Ce fichier ne fait que lancer scripts\TradingOS.Launcher.ps1 (ADR 0039).
rem  Il ne change aucune politique d'execution : -ExecutionPolicy Bypass ne vaut
rem  que pour ce processus.
rem
rem  Pause finale : seulement SANS argument (c'est le double-clic), pour que la
rem  fenetre ne se ferme pas sur le resultat. Avec un argument, jamais : un .bat
rem  lance depuis PowerShell, Python ou un planificateur tourne aussi sous
rem  "cmd /c". Variable TRADINGOS_NOPAUSE=1 : jamais de pause.
rem ---------------------------------------------------------------------------
setlocal
set "TRADINGOS_SHELL=powershell.exe"
where pwsh.exe >nul 2>&1
if not errorlevel 1 set "TRADINGOS_SHELL=pwsh.exe"
rem  Docker Desktop (ADR 0038, A11, decision d'Exhorte du 2026-11-22 : le lancer) : demarre s'il ne repond pas, seulement avant Full et Infrastructure
rem  (jamais avant Status, Stop, Doctor ni MT5). Un echec ne change rien : le lanceur dit lui-meme que Docker ne repond pas.
rem  Variable TRADINGOS_NODOCKERSTART=1 : n'y toucher jamais.
set "TRADINGOS_PRESTART=1"
for %%M in (Status Stop Doctor MT5) do if /i "%~1"=="%%M" set "TRADINGOS_PRESTART="
if defined TRADINGOS_NODOCKERSTART set "TRADINGOS_PRESTART="
if defined TRADINGOS_PRESTART if exist "%~dp0scripts\TradingOS.Docker.ps1" "%TRADINGOS_SHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\TradingOS.Docker.ps1"
"%TRADINGOS_SHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\TradingOS.Launcher.ps1" %*
set "TRADINGOS_EXIT=%ERRORLEVEL%"
if defined TRADINGOS_NOPAUSE goto done
if not "%~1"=="" goto done
echo.
pause
:done
exit /b %TRADINGOS_EXIT%
