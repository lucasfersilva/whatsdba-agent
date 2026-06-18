"""
WhatsDBA Agent — roda no servidor do cliente.
Coleta métricas dos bancos configurados e envia ao servidor SaaS.

Modos de operação:
  INSTANCES (recomendado) — descobre automaticamente todos os bancos da instância
  DATABASES (legado)      — lista manual de bancos no .env
"""

import logging
import time
import json
import socket
import requests
import schedule
from config import LICENSE_KEY, SERVER_URL, COLLECT_INTERVAL, DATABASES, INSTANCES
from collectors import collect, discover_databases
from updater import check_and_update, get_version

# Hostname desta máquina — identifica a instância no servidor SaaS
AGENT_HOSTNAME = socket.gethostname()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

HEADERS = {
    "X-License-Key": LICENSE_KEY,
    "Content-Type": "application/json",
}

# Cache de bancos descobertos por instância — atualizado a cada ciclo de coleta
# Chave: label/host da instância → lista de cfgs de banco
_discovered_cache: dict[str, list] = {}


def _send_metric(db_cfg: dict):
    """Coleta e envia métricas de um único banco."""
    try:
        logger.info(f"  Coletando [{db_cfg['type'].upper()}] {db_cfg['name']} ...")
        data = collect(db_cfg)
        data["hostname"] = AGENT_HOSTNAME

        resp = requests.post(
            f"{SERVER_URL}/api/metrics",
            headers=HEADERS,
            json=data,
            timeout=15,
        )

        if resp.status_code == 200:
            logger.info(f"  ✓ {db_cfg['name']} enviado")
        elif resp.status_code == 401:
            logger.error("  ✗ Chave de licença inválida ou expirada.")
        elif resp.status_code == 403:
            logger.error("  ✗ Servidor não autorizado para esta chave.")
        else:
            logger.error(f"  ✗ HTTP {resp.status_code} — {resp.text[:200]}")

    except requests.ConnectionError:
        logger.error(f"  ✗ Sem conexão com o servidor SaaS ({SERVER_URL})")
    except Exception as e:
        logger.error(f"  ✗ Erro em {db_cfg.get('name')}: {e}")


def run_collection():
    """
    Coleta métricas de todos os bancos e envia ao servidor.
    Suporta modo INSTANCES (auto-discovery) e DATABASES (legado).
    """
    if INSTANCES:
        # ── Modo auto-discovery ───────────────────────────────────────────────
        for instance_cfg in INSTANCES:
            label = instance_cfg.get("label") or instance_cfg["host"]
            logger.info(f"── Instância: {label} ──────────────────────────────")

            # Redescobre bancos a cada coleta (captura bancos novos/removidos)
            dbs = discover_databases(instance_cfg)
            if not dbs:
                logger.warning(f"  Nenhum banco encontrado em {label}")
                continue

            _discovered_cache[label] = dbs
            for db_cfg in dbs:
                _send_metric(db_cfg)

    elif DATABASES:
        # ── Modo legado ───────────────────────────────────────────────────────
        for db_cfg in DATABASES:
            _send_metric(db_cfg)

    else:
        logger.warning("Nenhum banco ou instância configurado. Verifique o .env.")


def validate_license() -> bool:
    """Valida a licença antes de iniciar a coleta."""
    if not LICENSE_KEY:
        logger.error("WHATSDBA_LICENSE_KEY não configurado. Defina no arquivo .env")
        return False
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/license/validate",
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            info = resp.json()
            logger.info(
                f"Licença válida — plano: {info.get('plan', 'N/A')} | "
                f"instâncias: {info.get('servers_used', 0)}/{info.get('servers_allowed', 0)}"
            )
            return True
        else:
            logger.error(f"Licença rejeitada: {resp.json().get('detail', 'Erro desconhecido')}")
            return False
    except Exception as e:
        logger.error(f"Não foi possível validar a licença: {e}")
        return False


def main():
    logger.info("=" * 50)
    logger.info(f"  WhatsDBA Agent v{get_version()} iniciando...")
    logger.info("=" * 50)

    if not validate_license():
        logger.error("Agente encerrado por falha na validação da licença.")
        return

    # ── Checa atualização antes de iniciar coleta ─────────────────────────
    if check_and_update(SERVER_URL, HEADERS):
        # Se retornou True, uma atualização foi aplicada e o processo vai reiniciar
        logger.info("Reiniciando para aplicar atualização...")
        return

    mode = "auto-discovery" if INSTANCES else "legado (DATABASES)"
    total = len(INSTANCES) if INSTANCES else len(DATABASES)
    logger.info(f"Modo: {mode} | {total} instância(s)/banco(s) | intervalo: {COLLECT_INTERVAL}s")

    # Primeira coleta imediata
    run_collection()

    # Coletas periódicas + checagem de atualização a cada ciclo
    schedule.every(COLLECT_INTERVAL).seconds.do(run_collection)
    schedule.every(COLLECT_INTERVAL).seconds.do(
        lambda: check_and_update(SERVER_URL, HEADERS)
    )

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
