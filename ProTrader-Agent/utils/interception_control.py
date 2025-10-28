"""Utilities to manage the Interception driver lifecycle.

This module encapsulates the PowerShell logic required to re-enable the
Interception driver at startup (if it has been disabled previously) and to
cleanly disable it again once the agent shuts down. The implementation mirrors
existing administrative scripts that toggle the driver through registry edits
and requires Windows with administrative privileges.
"""

from __future__ import annotations

import platform
import subprocess
import textwrap
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_SERVICE_REGISTRY_PATHS = (
    "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\interception",
    "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\keyboard",
    "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\mouse",
)

_REACTIVATE_SCRIPT = textwrap.dedent(
    r"""
    # === Restauration des paramètres Interception ===
    $bk = "$env:PUBLIC\InterceptionBackup"
    foreach($f in "svc_keyboard.reg","svc_mouse.reg","class_kbd.reg","class_mouse.reg"){
      $p = Join-Path $bk $f
      if (Test-Path $p){ reg import $p | Out-Null }
    }
    Write-Host "♻️ Registre restauré. Redémarrage dans 10 secondes..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    Restart-Computer -Force
    """
)

_DISABLE_SCRIPT = textwrap.dedent(
    r"""
    # === Interception - Désactivation SANS désinstaller (réversible) ===
    # ⚙️ Nécessite PowerShell en mode administrateur
    # 💾 Crée une sauvegarde avant toute modification
    # 🔁 Redémarre automatiquement le PC à la fin

    $ErrorActionPreference = "Stop"

    Write-Host "🛠 DÉSACTIVATION D'INTERCEPTION EN COURS..." -ForegroundColor Yellow

    # 1) Sauvegarde des clés du registre
    $bk = "$env:PUBLIC\InterceptionBackup"
    New-Item -ItemType Directory -Force -Path $bk | Out-Null
    reg export "HKLM\SYSTEM\CurrentControlSet\Services\keyboard" "$bk\svc_keyboard.reg" /y 2>$null
    reg export "HKLM\SYSTEM\CurrentControlSet\Services\mouse"    "$bk\svc_mouse.reg" /y 2>$null
    reg export "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4D36E96B-E325-11CE-BFC1-08002BE10318}" "$bk\class_kbd.reg" /y 2>$null
    reg export "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4D36E96F-E325-11CE-BFC1-08002BE10318}" "$bk\class_mouse.reg" /y 2>$null
    Write-Host "💾 Sauvegarde créée dans $bk" -ForegroundColor Cyan

    # 2) Mettre les services Interception en "Disabled" (Start=4)
    function Disable-ServiceIfExists($name){
      $key = "HKLM:\SYSTEM\CurrentControlSet\Services\$name"
      if (Test-Path $key){
        Set-ItemProperty -Path $key -Name Start -Value 4 -Type DWord -ErrorAction SilentlyContinue
        Write-Host "🔒 Service '$name' désactivé." -ForegroundColor Gray
      }
    }
    Disable-ServiceIfExists "interception"
    Disable-ServiceIfExists "keyboard"
    Disable-ServiceIfExists "mouse"

    # 3) Nettoyage des UpperFilters pour clavier et souris
    function Clean-UpperFilters($classGuid, $keep){
      $key = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\$classGuid"
      if (Test-Path $key){
        $val = (Get-ItemProperty -Path $key -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters
        if ($val){
          $new = @()
          foreach($f in $val){
            if ($keep -contains $f.ToLower()){
              $new += $f
            } else {
              Write-Host "🧹 Retrait du filtre '$f' sur $classGuid" -ForegroundColor Gray
            }
          }
          if ($new.Count -gt 0){
            Set-ItemProperty -Path $key -Name UpperFilters -Value $new
          } else {
            Remove-ItemProperty -Path $key -Name UpperFilters -ErrorAction SilentlyContinue
          }
        }
      }
    }
    Clean-UpperFilters "{4D36E96B-E325-11CE-BFC1-08002BE10318}" @("kbdclass")
    Clean-UpperFilters "{4D36E96F-E325-11CE-BFC1-08002BE10318}" @("mouclass")

    Write-Host ""
    Write-Host "✅ Interception désactivé au niveau système (réversible)." -ForegroundColor Green
    Write-Host "🔁 Le PC va redémarrer dans 10 secondes..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10

    # 4) Redémarrage automatique
    Restart-Computer -Force
    """
)


def ensure_interception_ready() -> None:
    """Ensure the Interception driver is enabled before the agent starts.

    On Windows, we inspect a few registry keys that are flipped to ``Start = 4``
    when the driver has been disabled. If any of these services are disabled we
    trigger the provided restoration script, which re-imports the previously
    saved registry state and forces a reboot.
    """

    if not _is_windows():
        logger.debug("Interception check skipped (non-Windows platform)")
        return

    if _is_interception_ready():
        logger.info("Interception driver already enabled")
        return

    logger.warning(
        "Interception driver detected as disabled; restoring backup and rebooting"
    )
    _run_powershell_script(_REACTIVATE_SCRIPT, "restore Interception settings")


def disable_interception() -> None:
    """Disable the Interception driver before the agent exits (Windows only)."""

    if not _is_windows():
        logger.debug("Interception disable skipped (non-Windows platform)")
        return

    if not _is_interception_ready():
        logger.info("Interception driver already disabled; skipping shutdown script")
        return

    logger.info("Disabling Interception driver before shutdown")
    try:
        _run_powershell_script(_DISABLE_SCRIPT, "disable Interception")
    except subprocess.CalledProcessError:
        logger.exception("Failed to disable Interception driver via PowerShell")
        raise


def _is_windows() -> bool:
    return platform.system().lower().startswith("windows")


def _is_interception_ready() -> bool:
    """Return True when every monitored service is not explicitly disabled."""

    for path in _SERVICE_REGISTRY_PATHS:
        value = _read_registry_dword(path, "Start")
        if value == 4:
            logger.debug("Registry Start=4 detected for %s", path)
            return False
    return True


def _read_registry_dword(path: str, name: str) -> Optional[int]:
    """Read a DWORD registry value via PowerShell and return it as an int."""

    ps_path = path.replace('"', '`"')
    ps_name = name.replace('"', '`"')
    script = (
        f"(Get-ItemProperty -Path \"{ps_path}\" -Name \"{ps_name}\" "
        "-ErrorAction SilentlyContinue).{name}"
    )

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.warning("PowerShell not found; assuming Interception is ready")
        return None

    raw_value = result.stdout.strip()
    if not raw_value:
        return None

    try:
        return int(raw_value)
    except ValueError:
        logger.debug("Unexpected registry value '%s' for %s", raw_value, path)
        return None


def _run_powershell_script(script: str, description: str) -> None:
    """Execute a multi-line PowerShell script."""

    dedented = textwrap.dedent(script).strip()
    logger.debug("Executing PowerShell script to %s", description)
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                dedented,
            ],
            check=True,
        )
    except FileNotFoundError:
        logger.error(
            "PowerShell executable not found while attempting to %s",
            description,
        )
        raise
