"""
Coletor de métricas para MySQL.
Coleta: queries caras (slow log / performance_schema), processlist, status global.
"""

import pymysql
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_SYSTEM_DBS_MYSQL = {"information_schema", "performance_schema", "mysql", "sys"}


def discover_databases(instance_cfg: dict) -> list[dict]:
    """
    Conecta no MySQL e retorna lista de dicts — um por banco de usuário encontrado.
    """
    try:
        conn = pymysql.connect(
            host=instance_cfg["host"],
            port=instance_cfg.get("port", 3306),
            user=instance_cfg["user"],
            password=instance_cfg["password"],
            database="information_schema",
            connect_timeout=5,
            cursorclass=pymysql.cursors.DictCursor,
        )
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES")
        rows = [r["Database"] for r in cursor.fetchall()
                if r["Database"].lower() not in _SYSTEM_DBS_MYSQL]
        conn.close()

        include = {d.lower() for d in instance_cfg.get("include_databases", [])}
        exclude = {d.lower() for d in instance_cfg.get("exclude_databases", [])}

        result = []
        for db_name in rows:
            if exclude and db_name.lower() in exclude:
                continue
            if include and db_name.lower() not in include:
                continue
            cfg = dict(instance_cfg)
            cfg["name"]     = db_name
            cfg["database"] = db_name
            result.append(cfg)

        label = instance_cfg.get("label") or instance_cfg["host"]
        logger.info(f"[{label}] {len(result)} banco(s) MySQL descoberto(s): {[r['name'] for r in result]}")
        return result

    except Exception as e:
        label = instance_cfg.get("label") or instance_cfg.get("host", "?")
        logger.error(f"[{label}] Falha ao descobrir bancos MySQL: {e}")
        return []


def get_connection(cfg: dict):
    return pymysql.connect(
        host=cfg["host"],
        port=cfg.get("port", 3306),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg.get("database", "information_schema"),
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
    )


def collect(cfg: dict) -> dict:
    """Coleta todas as métricas do MySQL e retorna um dict."""
    result = {
        "db_name": cfg["name"],
        "db_type": "mysql",
        "host": cfg["host"],
        "collected_at": datetime.utcnow().isoformat(),
        "status": "offline",
        "metrics": {},
        "expensive_queries": [],
        "deadlocks": [],
        "active_sessions": [],
        "alerts": [],
    }

    try:
        conn = get_connection(cfg)
        result["status"] = "online"
        cursor = conn.cursor()

        # ── Métricas globais ─────────────────────────────────────────────────
        cursor.execute("SHOW GLOBAL STATUS")
        status = {row["Variable_name"]: row["Value"] for row in cursor.fetchall()}
        cursor.execute("SHOW GLOBAL VARIABLES LIKE 'max_connections'")
        vars_row = cursor.fetchone()
        max_conn = int(vars_row["Value"]) if vars_row else 0

        # Memória InnoDB buffer pool
        bp_size   = int(status.get("Innodb_buffer_pool_bytes_data", 0)) + int(status.get("Innodb_buffer_pool_bytes_dirty", 0))
        bp_total  = int(status.get("Innodb_buffer_pool_pages_total", 1)) * 16384  # 16KB por página
        mem_mb    = round(bp_size / 1024 / 1024, 1)
        # Conexões %
        conn_pct  = round(int(status.get("Threads_connected", 0)) / max_conn * 100, 1) if max_conn else 0

        result["metrics"] = {
            "queries_per_sec":            int(status.get("Queries", 0)),
            "connections":                int(status.get("Threads_connected", 0)),
            "max_connections":            max_conn,
            "connection_pct":             conn_pct,
            "aborted_connects":           int(status.get("Aborted_connects", 0)),
            "innodb_buffer_pool_reads":   int(status.get("Innodb_buffer_pool_reads", 0)),
            "innodb_buffer_pool_hit_rate": _buffer_pool_hit_rate(status),
            "slow_queries":               int(status.get("Slow_queries", 0)),
            "uptime_seconds":             int(status.get("Uptime", 0)),
            "total_memory_mb":            mem_mb,
            "cpu_pct":                    0,   # MySQL não expõe CPU diretamente
        }

        if result["metrics"]["slow_queries"] > 0:
            result["alerts"].append({
                "level": "warning",
                "message": f"{result['metrics']['slow_queries']} slow queries acumuladas",
                "type": "slow_query",
            })

        # ── Top 10 queries mais caras (performance_schema) ───────────────────
        cursor.execute("""
            SELECT
                DIGEST_TEXT AS query_text,
                COUNT_STAR AS execution_count,
                ROUND(AVG_TIMER_WAIT / 1e9, 2) AS avg_elapsed_ms,
                ROUND(SUM_TIMER_WAIT / 1e9, 2) AS total_elapsed_ms,
                ROUND(IF(COUNT_STAR > 0, SUM_ROWS_EXAMINED / COUNT_STAR, 0), 0) AS avg_rows_examined,
                ROUND(IF(COUNT_STAR > 0, SUM_ROWS_SENT / COUNT_STAR, 0), 0) AS avg_rows_sent,
                SCHEMA_NAME AS database_name,
                LAST_SEEN AS last_seen
            FROM performance_schema.events_statements_summary_by_digest
            WHERE DIGEST_TEXT IS NOT NULL
              AND SCHEMA_NAME IS NOT NULL
            ORDER BY AVG_TIMER_WAIT DESC
            LIMIT 10
        """)
        for row in cursor.fetchall():
            result["expensive_queries"].append({
                "query_text": (row["query_text"] or "").strip()[:1000],
                "execution_count": row["execution_count"],
                "avg_elapsed_ms": float(row["avg_elapsed_ms"] or 0),
                "total_elapsed_ms": float(row["total_elapsed_ms"] or 0),
                "avg_rows_examined": int(row["avg_rows_examined"] or 0),
                "avg_rows_sent": int(row["avg_rows_sent"] or 0),
                "database_name": row["database_name"],
                "last_seen": str(row["last_seen"]),
            })

        # ── Deadlock mais recente (InnoDB status) ────────────────────────────
        cursor.execute("SHOW ENGINE INNODB STATUS")
        innodb_status = cursor.fetchone() or {}
        innodb_text = innodb_status.get("Status", "")
        if "LATEST DETECTED DEADLOCK" in innodb_text:
            start = innodb_text.find("LATEST DETECTED DEADLOCK")
            end = innodb_text.find("------------\nTRANSACTIONS", start)
            deadlock_block = innodb_text[start:end if end > 0 else start + 3000]

            # Extrai timestamp do deadlock
            import re as _re
            deadlock_time = "recente"
            m = _re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', deadlock_block)
            if m:
                deadlock_time = m.group(0)

            # Extrai query de cada transação
            def _innodb_query(block, marker):
                idx = block.find(marker)
                if idx < 0:
                    return ""
                seg = block[idx:]
                for kw in ["HOLDS THE LOCK", "WAITING FOR", "WE ROLL BACK", "(2) TRANSACTION"]:
                    ei = seg.find(kw)
                    if ei > 0:
                        seg = seg[:ei]
                        break
                lines = [l.strip() for l in seg.splitlines() if l.strip() and not l.startswith("***")]
                return " ".join(lines[1:6])[:1000]

            query1 = _innodb_query(deadlock_block, "(1) TRANSACTION:")
            query2 = _innodb_query(deadlock_block, "(2) TRANSACTION:")

            result["deadlocks"].append({
                "deadlock_time": deadlock_time,
                "victim_query": query2[:1000],      # MySQL cancela a 2ª transação
                "blocking_query": query1[:1000],
                "details": deadlock_block[:3000],
            })
            result["alerts"].append({
                "level": "critical",
                "message": "Deadlock detectado no InnoDB",
                "type": "deadlock",
            })

        # ── Sessões ativas / bloqueadas ──────────────────────────────────────
        cursor.execute("""
            SELECT
                ID AS session_id,
                USER AS login,
                HOST AS host,
                DB AS database_name,
                COMMAND AS command,
                TIME AS time_sec,
                STATE AS state,
                LEFT(INFO, 500) AS current_query
            FROM information_schema.PROCESSLIST
            WHERE COMMAND != 'Sleep'
            ORDER BY TIME DESC
            LIMIT 20
        """)
        for row in cursor.fetchall():
            result["active_sessions"].append({
                "session_id": row["session_id"],
                "login": row["login"],
                "host": row["host"],
                "database_name": row["database_name"],
                "command": row["command"],
                "time_sec": row["time_sec"],
                "state": row["state"],
                "current_query": (row["current_query"] or "").strip(),
            })

        # Bloqueios ativos (aguardando lock) por >= 60s
        BLOCKING_MIN_WAIT_SEC = 60
        LOCK_WAIT_STATES = {"Waiting for lock", "Waiting for table lock",
                            "Waiting for table metadata lock", "Locked",
                            "waiting for handler lock"}
        blocked = [
            s for s in result["active_sessions"]
            if (s["time_sec"] or 0) >= BLOCKING_MIN_WAIT_SEC
            and any(kw.lower() in (s.get("state") or "").lower()
                    for kw in ("waiting for", "locked"))
        ]
        if blocked:
            max_wait = max(s.get("time_sec", 0) for s in blocked)
            result["alerts"].append({
                "level": "warning",
                "message": f"{len(blocked)} sessão(ões) aguardando lock há {int(max_wait)}s ou mais",
                "type": "blocking",
            })

        # Queries longas (sem lock) rodando há mais de 60s
        long_running = [
            s for s in result["active_sessions"]
            if (s["time_sec"] or 0) >= BLOCKING_MIN_WAIT_SEC
            and not any(kw.lower() in (s.get("state") or "").lower()
                        for kw in ("waiting for", "locked"))
        ]
        if long_running:
            max_time = max(s.get("time_sec", 0) for s in long_running)
            result["alerts"].append({
                "level": "warning",
                "message": f"{len(long_running)} query(ies) rodando há {int(max_time)}s ou mais",
                "type": "long_running",
            })

        cursor.close()
        conn.close()

    except Exception as e:
        result["status"] = "offline"
        result["alerts"].append({
            "level": "critical",
            "message": f"Banco inacessível: {str(e)}",
            "type": "offline",
        })
        logger.error(f"[MySQL] {cfg['name']} erro: {e}")

    return result


def _buffer_pool_hit_rate(status: dict) -> float:
    reads = int(status.get("Innodb_buffer_pool_reads", 0))
    requests = int(status.get("Innodb_buffer_pool_read_requests", 1))
    if requests == 0:
        return 100.0
    return round((1 - reads / requests) * 100, 2)
