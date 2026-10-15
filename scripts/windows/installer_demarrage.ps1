<#
.SYNOPSIS
  Démarre automatiquement l'application (port 8082) et le worker des rapports avec Windows.

.DESCRIPTION
  Crée (ou remplace) une tâche planifiée lancée au démarrage du serveur, sans session ouverte :
  python manage.py superviser, qui lance l'application web et le worker, les relance s'ils
  s'arrêtent et permet de les redémarrer depuis l'administration (Système → Processus du serveur).
  Journaux : data\superviseur\*.log. À lancer dans un PowerShell « Exécuter en tant qu'administrateur »,
  depuis n'importe quel dossier, après avoir fermé les consoles runserver / qcluster ouvertes à la main.

.EXAMPLE
  .\scripts\windows\installer_demarrage.ps1 -OuvrirPareFeu -Demarrer
.EXAMPLE
  .\scripts\windows\installer_demarrage.ps1 -Utilisateur "DOMAINE\svc-stats" -Demarrer
.EXAMPLE
  .\scripts\windows\installer_demarrage.ps1 -Supprimer
#>
param(
  [int]$Port = 8082,
  # Compte qui exécute l'application. Vide : SYSTEM (aucun mot de passe à gérer). Utiliser un compte de
  # service si l'accès à la base KPI dépend d'un lecteur réseau, d'un VPN ou d'une authentification Windows.
  [string]$Utilisateur = "",
  [string]$NomTache = "Stats - application et worker",
  [switch]$OuvrirPareFeu,
  [switch]$Demarrer,
  [switch]$Supprimer
)
$ErrorActionPreference = "Stop"

if ($Supprimer) {
  Stop-ScheduledTask -TaskName $NomTache -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $NomTache -Confirm:$false
  Write-Host "Tâche « $NomTache » supprimée."
  return
}

$racine = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $racine ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python de l'environnement introuvable : $python (créer le .venv, voir README)." }
if (-not (Test-Path (Join-Path $racine ".env"))) { Write-Warning "Pas de .env dans $racine : réglages par défaut." }

$action = New-ScheduledTaskAction -Execute $python -Argument "manage.py superviser --port $Port" -WorkingDirectory $racine
$declencheur = New-ScheduledTaskTrigger -AtStartup
# Sans limite de durée ; relancée si elle s'arrête en erreur ; une seule instance à la fois.
$reglages = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if ($Utilisateur) {
  $identifiants = Get-Credential -UserName $Utilisateur -Message "Mot de passe du compte qui exécute l'application"
  Register-ScheduledTask -TaskName $NomTache -Action $action -Trigger $declencheur -Settings $reglages `
    -User $identifiants.UserName -Password $identifiants.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
} else {
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask -TaskName $NomTache -Action $action -Trigger $declencheur -Settings $reglages `
    -Principal $principal -Force | Out-Null
}
Write-Host "Tâche « $NomTache » créée : application sur le port $Port + worker, au démarrage du serveur."

if ($OuvrirPareFeu) {
  $regle = "Stats - port $Port"
  if (-not (Get-NetFirewallRule -DisplayName $regle -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $regle -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
  }
  Write-Host "Pare-feu : port $Port ouvert en entrée."
}

if ($Demarrer) {
  Start-ScheduledTask -TaskName $NomTache
  Write-Host "Tâche démarrée. Journaux : $racine\data\superviseur\ ; état : Administration > Processus du serveur."
}
