import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Licença e servidor ────────────────────────────────────────────────────────
LICENSE_KEY      = os.getenv("WHATSDBA_LICENSE_KEY", "")
SERVER_URL       = os.getenv("WHATSDBA_SERVER_URL", "http://localhost:8000")
COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL", "60"))

# MED-3: alerta se comunicação não estiver criptografada em produção
if SERVER_URL.startswith("http://") and "localhost" not in SERVER_URL and "127.0.0.1" not in SERVER_URL:
    logger.warning(
        "ATENÇÃO: WHATSDBA_SERVER_URL usa HTTP não criptografado. "
        "Credenciais e chave de licença trafegam em texto plano! "
        "Use HTTPS em produção."
    )

# ── Modo INSTANCES (novo — recomendado) ───────────────────────────────────────
# O agente descobre automaticamente todos os bancos da instância.
# Formato mínimo:
#   INSTANCES=[{"type":"sqlserver","host":"127.0.0.1","port":1433,"user":"sa","password":"senha"}]
#
# Opcional por instância:
#   "label"             : nome amigável para logs (padrão: host)
#   "include_databases" : lista de bancos a incluir (padrão: todos)
#   "exclude_databases" : lista de bancos a excluir (padrão: nenhum)
#
# Exemplo com filtro:
#   INSTANCES=[{"type":"sqlserver","host":"10.0.0.1","user":"sa","password":"s3cr3t",
#               "exclude_databases":["Teste","Homologacao"]}]

def _load_instances() -> list:
    raw = os.getenv("INSTANCES", "").strip()
    if not raw:
        return []
    try:
        instances = json.loads(raw)
        if not isinstance(instances, list):
            raise ValueError("INSTANCES deve ser uma lista JSON")
        for inst in instances:
            for field in ("type", "host", "user", "password"):
                if field not in inst:
                    raise ValueError(f"Campo obrigatório ausente em INSTANCES: '{field}'")
        labels = [i.get("label") or i["host"] for i in instances]
        logger.info(f"{len(instances)} instância(s) configurada(s): {labels}")
        return instances
    except json.JSONDecodeError as e:
        logger.error(f"INSTANCES inválido — erro de JSON: {e}")
        return []
    except ValueError as e:
        logger.error(f"INSTANCES inválido: {e}")
        return []

INSTANCES = _load_instances()


# ── Modo DATABASES (legado — ainda funciona) ──────────────────────────────────
# Usado quando INSTANCES não está definido.
# Cada entrada precisa de: type, name, host, user, password, database.

def _load_databases() -> list:
    if INSTANCES:
        return []  # INSTANCES tem prioridade
    raw = os.getenv("DATABASES", "").strip()
    if not raw:
        logger.warning(
            "Nenhuma instância configurada.\n"
            "Defina INSTANCES no .env (recomendado):\n"
            '  INSTANCES=[{"type":"sqlserver","host":"127.0.0.1","port":1433,'
            '"user":"sa","password":"senha"}]\n'
            "Ou use o modo legado DATABASES para listar cada banco manualmente."
        )
        return []
    try:
        dbs = json.loads(raw)
        if not isinstance(dbs, list):
            raise ValueError("DATABASES deve ser uma lista JSON")
        for db in dbs:
            for field in ("type", "name", "host", "user", "password"):
                if field not in db:
                    raise ValueError(f"Campo obrigatório ausente em DATABASES: '{field}'")
        logger.info(f"{len(dbs)} banco(s) configurado(s) (modo legado): {[d['name'] for d in dbs]}")
        return dbs
    except json.JSONDecodeError as e:
        logger.error(f"DATABASES inválido — erro de JSON: {e}")
        return []
    except ValueError as e:
        logger.error(f"DATABASES inválido: {e}")
        return []

DATABASES = _load_databases()
