import os
import subprocess


def open_dofus():
    os.startfile(r"assets\Dofus.lnk")


def close_dofus(force: bool = True) -> bool:
    """
    Ferme toutes les tâches 'Dofus.exe' (Windows).
    - force=True : équivalent 'Fin de tâche' ( /F ) + inclut les processus enfants ( /T )
    Retourne True si au moins une tâche a été fermée, False sinon.
    """
    cmd = ["taskkill", "/IM", "Dofus.exe"]
    if force:
        cmd += ["/F", "/T"]
    try:
        # capture_output=True pour éviter le spam console; text=True pour décoder proprement
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        # Code 0 = succès, 128 = aucun processus trouvé (pas grave), autres = erreur
        if res.returncode == 0:
            return True
        if "not found" in (res.stderr or "").lower() or res.returncode == 128:
            return False
        # Si autre erreur, on la remonte pour debug
        raise RuntimeError(f"taskkill error {res.returncode}: {res.stderr.strip() or res.stdout.strip()}")
    except FileNotFoundError:
        raise RuntimeError("Commande 'taskkill' introuvable (Windows requis).")

if __name__ == "__main__":
    close_dofus()

