"""
WhatsDBA Agent — Auto-updater

Checa a versão mais recente no servidor SaaS e se auto-atualiza.

Fluxo:
  1. GET /api/agent/version  → {"version": "1.3.0", "download_url": "...", "checksum_sha256": "..."}
  2. Compara com AGENT_VERSION local
  3. Se há nova versão:
     - Baixa o novo exe para um arquivo temporário
     - Valida checksum SHA-256
     - Substitui o exe atual e reinicia (Windows: via bat; Linux: exec)

Segurança:
  - Somente atualiza se o servidor retornar 200 com chave de licença válida
  - Valida SHA-256 antes de qualquer execução
  - Em caso de falha, mantém versão atual sem interromper coleta

Modo frozen (PyInstaller):
  sys.frozen == True → rodando como .exe compilado, usa sys.executable
  caso contrário     → modo dev (git), skip automático da atualização
"""

import hashlib
import logging
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ── Versão atual do agent ─────────────────────────────────────────────────────
# Atualizar a cada release (também usado no installer.iss e no GitHub Actions)
AGENT_VERSION = "1.2.0"

# Endpoint do servidor SaaS que retorna info de versão
VERSION_ENDPOINT = "/api/agent/version"

# Intervalo entre checagens de versão (segundos) — padrão: 6 horas
UPDATE_CHECK_INTERVAL = int(os.getenv("UPDATE_CHECK_INTERVAL", str(6 * 3600)))

_last_check: float = 0


def _is_frozen() -> bool:
    """True quando rodando como executável PyInstaller (.exe)."""
    return getattr(sys, "frozen", False)


def check_and_update(server_url: str, headers: dict) -> bool:
    """
    Checa e aplica atualização se disponível.

    Retorna True se uma atualização foi aplicada (agente vai reiniciar).
    Retorna False se não há atualização ou ocorreu erro (continua rodando).
    """
    global _last_check

    # Em modo dev (sem PyInstaller), não atualiza automaticamente
    if not _is_frozen():
        logger.debug("[updater] Modo dev — auto-update desabilitado (use git pull)")
        return False

    now = time.monotonic()
    if now - _last_check < UPDATE_CHECK_INTERVAL:
        return False
    _last_check = now

    try:
        resp = requests.get(
            f"{server_url}{VERSION_ENDPOINT}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.debug(f"[updater] Servidor retornou {resp.status_code}, pulando checagem")
            return False

        info = resp.json()
        latest = info.get("version", "")
        download_url = info.get("download_url", "")
        expected_sha256 = info.get("checksum_sha256", "")

        if not latest or not download_url:
            return False

        if latest == AGENT_VERSION:
            logger.info(f"[updater] Versão atual ({AGENT_VERSION}) é a mais recente")
            return False

        # Versão nova disponível
        logger.info(f"[updater] Nova versão disponível: {AGENT_VERSION} → {latest}")
        logger.info(f"[updater] Baixando de {download_url} ...")

        return _download_and_apply(download_url, expected_sha256, latest)

    except requests.ConnectionError:
        logger.debug("[updater] Sem conexão para checar atualizações")
    except Exception as e:
        logger.warning(f"[updater] Erro ao checar atualização: {e}")

    return False


def _download_and_apply(url: str, expected_sha256: str, new_version: str) -> bool:
    """
    Baixa o novo executável, valida checksum e agenda substituição.
    Retorna True se a atualização foi agendada com sucesso.
    """
    current_exe = Path(sys.executable)
    tmp_dir = Path(tempfile.gettempdir())
    tmp_exe = tmp_dir / f"whatsdba-agent-{new_version}.exe"

    try:
        # Download com progresso
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()

        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        sha = hashlib.sha256()

        with open(tmp_exe, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                sha.update(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    logger.info(f"[updater] Download: {pct:.0f}%")

        # Valida checksum — OBRIGATÓRIO, sem exceção
        actual_sha256 = sha.hexdigest()
        if not expected_sha256:
            logger.error("[updater] Servidor não forneceu checksum SHA-256. Atualização cancelada por segurança.")
            tmp_exe.unlink(missing_ok=True)
            return False
        if actual_sha256 != expected_sha256:
            logger.error(
                f"[updater] Checksum inválido! Esperado: {expected_sha256} | "
                f"Obtido: {actual_sha256}. Atualização cancelada."
            )
            tmp_exe.unlink(missing_ok=True)
            return False

        logger.info(f"[updater] Download concluído, checksum OK")

        # Aplica substituição
        if platform.system() == "Windows":
            return _apply_windows(current_exe, tmp_exe, new_version)
        else:
            return _apply_unix(current_exe, tmp_exe)

    except Exception as e:
        logger.error(f"[updater] Falha no download: {e}")
        tmp_exe.unlink(missing_ok=True)
        return False


def _apply_windows(current_exe: Path, new_exe: Path, new_version: str) -> bool:
    """
    No Windows o exe em uso não pode ser sobrescrito diretamente.
    Cria um .bat que aguarda o processo terminar, substitui e reinicia o serviço.
    """
    bat_path = current_exe.parent / "_whatsdba_update.bat"
    bat_content = f"""@echo off
timeout /t 3 /nobreak >nul
copy /y "{new_exe}" "{current_exe}"
del "{new_exe}"
del "%~f0"
sc start WhatsDBA-Agent
"""
    bat_path.write_text(bat_content, encoding="ascii")

    # Executa o bat de forma independente e encerra o processo atual
    subprocess.Popen(
        ["cmd.exe", "/C", str(bat_path)],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    logger.info(f"[updater] Atualização para {new_version} agendada — reiniciando serviço...")
    return True


def _apply_unix(current_exe: Path, new_exe: Path) -> bool:
    """
    No Linux/macOS o arquivo pode ser substituído enquanto em uso.
    Substitui e reinicia via exec() para que o systemd gerencie o restart.
    """
    os.chmod(new_exe, 0o755)
    os.replace(new_exe, current_exe)
    logger.info("[updater] Executável substituído — reiniciando agente...")
    os.execv(str(current_exe), sys.argv)  # substitui processo atual
    return True  # nunca chega aqui


def get_version() -> str:
    return AGENT_VERSION
