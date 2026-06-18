"""
Coletor de métricas para SQL Server.
Coleta: queries caras, deadlocks, status, sessões ativas, uso de CPU/memória.
"""

import pyodbc
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Bancos de sistema que nunca devem ser monitorados
_SYSTEM_DBS = {"master", "tempdb", "model", "msdb", "distribution", "reportserver", "reportservertempdb"}

# ── Cache de deadlocks por instância ─────────────────────────────────────────
# A query do ring buffer XE é cara (CAST XML do buffer inteiro) e retorna
# dados de nível de INSTÂNCIA — não faz sentido rodar N vezes por ciclo.
# Cache: (host, port) → {"ts": monotonic, "data": [...]}
_deadlock_cache: dict[tuple, dict] = {}
_DEADLOCK_CACHE_TTL = 50  # segundos — ligeiramente abaixo do COLLECT_INTERVAL padrão (60s)


def discover_databases(instance_cfg: dict) -> list[dict]:
    """
    Conecta na instância SQL Server via 'master' e retorna lista de dicts,
    um por banco de dados de usuário encontrado.

    instance_cfg precisa de: type, host, user, password, port (opcional).
    Retorna lista de cfgs prontos para passar ao collect().
    """
    master_cfg = dict(instance_cfg)
    master_cfg["database"] = "master"
    master_cfg["name"] = "master"  # temporário — será substituído

    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={instance_cfg['host']},{instance_cfg.get('port', 1433)};"
            f"DATABASE=master;"
            f"UID={instance_cfg['user']};"
            f"PWD={instance_cfg['password']};"
            f"Connection Timeout=5;"
        )
        conn   = pyodbc.connect(conn_str, timeout=5)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name
            FROM   sys.databases
            WHERE  state_desc = 'ONLINE'
              AND  is_read_only = 0
              AND  LOWER(name) NOT IN (
                       'master','tempdb','model','msdb',
                       'distribution','reportserver','reportservertempdb'
                   )
            ORDER BY name
        """)
        rows = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Filtra pela allow/denylist se configurada na instância
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
        logger.info(f"[{label}] {len(result)} banco(s) descoberto(s): {[r['name'] for r in result]}")
        return result

    except Exception as e:
        label = instance_cfg.get("label") or instance_cfg.get("host", "?")
        logger.error(f"[{label}] Falha ao descobrir bancos: {e}")
        return []


def get_connection(cfg: dict):
    """
    Conecta diretamente no banco monitorado para que DB_ID() retorne o ID correto.

    Prioridade:
      1. campo 'database' se definido e NÃO for 'master' / 'sys' / vazio
      2. campo 'name' (fallback para clientes que deixaram database='master'
         seguindo o .env.example antigo)
      3. 'master' como último recurso

    O campo 'database' deve conter o nome REAL do banco no SQL Server,
    não 'master'. Ex: {"database": "SCOS"} não {"database": "master"}.
    """
    explicit_db = (cfg.get("database") or "").strip()
    name_db     = (cfg.get("name")     or "").strip()

    GENERIC = {"master", "sys", "tempdb", "model", "msdb", ""}

    if explicit_db.lower() not in GENERIC:
        target_db = explicit_db                         # configurado corretamente
    elif name_db.lower() not in GENERIC:
        target_db = name_db                             # fallback via 'name'
        logger.warning(
            f"[{name_db}] 'database' está como '{explicit_db or 'vazio'}' — "
            f"conectando via name='{name_db}'. "
            "Defina 'database':'<nome_real_do_banco>' no .env para remover este aviso."
        )
    else:
        target_db = "master"

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={cfg['host']},{cfg.get('port', 1433)};"
        f"DATABASE={target_db};"
        f"UID={cfg['user']};"
        f"PWD={cfg['password']};"
        f"Connection Timeout=5;"
    )
    return pyodbc.connect(conn_str, timeout=5)


def _get_deadlocks_cached(instance_key: tuple, conn) -> list:
    """
    Retorna deadlocks das últimas 24h do ring buffer XE.

    Usa cache TTL por instância: o ring buffer é dado de nível de instância,
    não de banco. Em ambientes com N bancos monitorados, sem cache a mesma
    query cara rodaria N vezes por ciclo. Aqui roda 1×, as demais usam cache.
    """
    cached = _deadlock_cache.get(instance_key)
    if cached and (time.monotonic() - cached["ts"]) < _DEADLOCK_CACHE_TTL:
        logger.debug(f"[deadlock cache HIT] {instance_key}")
        return cached["data"]

    logger.debug(f"[deadlock cache MISS] {instance_key} — consultando ring buffer")
    deadlocks = []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                xdr.value('@timestamp', 'datetime2') AS deadlock_time,
                xdr.value('(data[@name="xml_report"]/value/deadlock/victim-list/victimProcess/@id)[1]', 'nvarchar(50)') AS victim_id,
                xdr.value('(data[@name="xml_report"]/value/deadlock/process-list/process[1]/inputbuf)[1]', 'nvarchar(2000)') AS query1,
                xdr.value('(data[@name="xml_report"]/value/deadlock/process-list/process[2]/inputbuf)[1]', 'nvarchar(2000)') AS query2,
                xdr.value('(data[@name="xml_report"]/value/deadlock/process-list/process[1]/@id)[1]', 'nvarchar(50)') AS proc_id1,
                xdr.value('(data[@name="xml_report"]/value/deadlock/process-list/process[1]/@loginname)[1]', 'nvarchar(100)') AS login1,
                xdr.value('(data[@name="xml_report"]/value/deadlock/process-list/process[2]/@loginname)[1]', 'nvarchar(100)') AS login2,
                xdr.value('(data[@name="xml_report"]/value/deadlock/process-list/process[1]/@waitresource)[1]', 'nvarchar(500)') AS wait_resource
            FROM (
                SELECT CAST(target_data AS XML) AS target_data
                FROM sys.dm_xe_session_targets xet
                JOIN sys.dm_xe_sessions xes ON xes.address = xet.event_session_address
                WHERE xes.name = 'system_health'
                  AND xet.target_name = 'ring_buffer'
            ) AS data
            CROSS APPLY target_data.nodes('//RingBufferTarget/event[@name="xml_deadlock_report"]') AS xEventData(xdr)
            WHERE xdr.value('@timestamp', 'datetime2') >= DATEADD(HOUR, -24, GETUTCDATE())
            ORDER BY deadlock_time DESC
            OPTION (MAXDOP 1)
        """)
        for row in cursor.fetchall():
            deadlock_time, victim_id, q1, q2, proc_id1, login1, login2, wait_resource = row
            if victim_id and victim_id == proc_id1:
                victim_query, blocking_query = q1, q2
                login_victim, login_blocking = login1, login2
            else:
                victim_query, blocking_query = q2, q1
                login_victim, login_blocking = login2, login1

            deadlocks.append({
                "deadlock_time": str(deadlock_time),
                "victim_query": (victim_query or "").strip()[:2000],
                "blocking_query": (blocking_query or "").strip()[:2000],
                "wait_resource": (wait_resource or "").strip()[:500],
                "login_victim": login_victim or "",
                "login_blocking": login_blocking or "",
            })
        cursor.close()
    except Exception as e:
        logger.warning(f"[deadlock] Erro ao ler ring buffer: {e}")

    _deadlock_cache[instance_key] = {"ts": time.monotonic(), "data": deadlocks}
    return deadlocks


def collect(cfg: dict) -> dict:
    """Coleta todas as métricas do SQL Server e retorna um dict."""
    result = {
        "db_name": cfg["name"],
        "db_type": "sqlserver",
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

        # ── Métricas gerais ──────────────────────────────────────────────────
        cursor.execute("""
            SELECT
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'Batch Requests/sec' AND object_name LIKE '%SQL Statistics%') AS batch_requests_sec,
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'SQL Compilations/sec' AND object_name LIKE '%SQL Statistics%') AS compilations_sec,
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'User Connections' AND object_name LIKE '%General Statistics%') AS user_connections,
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'Total Server Memory (KB)' AND object_name LIKE '%Memory Manager%') AS total_memory_kb,
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'Target Server Memory (KB)' AND object_name LIKE '%Memory Manager%') AS target_memory_kb,
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'Buffer cache hit ratio' AND object_name LIKE '%Buffer Manager%') AS buf_cache_hit,
                (SELECT cntr_value FROM sys.dm_os_performance_counters
                 WHERE counter_name = 'Page life expectancy' AND object_name LIKE '%Buffer Manager%') AS page_life_exp
        """)
        row = cursor.fetchone()
        if row:
            total_mb  = round((row[3] or 0) / 1024, 1)
            target_mb = round((row[4] or 0) / 1024, 1)
            mem_pct   = round(total_mb / target_mb * 100, 1) if target_mb else 0.0
            result["metrics"] = {
                "batch_requests_sec": row[0],
                "compilations_sec":   row[1],
                "user_connections":   row[2],
                "total_memory_mb":    total_mb,
                "target_memory_mb":   target_mb,
                "memory_pct":         mem_pct,
                "buffer_cache_hit":   row[5],
                "page_life_exp":      row[6],
            }

        # CPU % do SQL Server via ring buffer (NOLOCK + sem LIKE para maior compatibilidade)
        try:
            cursor.execute("""
                SELECT TOP 1
                    record.value('(./Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]','int') AS sql_cpu_pct,
                    record.value('(./Record/SchedulerMonitorEvent/SystemHealth/SystemIdle)[1]','int')          AS idle_pct
                FROM (
                    SELECT TOP 1 CONVERT(XML, record) AS record
                    FROM sys.dm_os_ring_buffers WITH (NOLOCK)
                    WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR'
                    ORDER BY timestamp DESC
                ) AS rd
                WHERE record IS NOT NULL
            """)
            crow = cursor.fetchone()
            if crow and crow[0] is not None and result["metrics"] is not None:
                result["metrics"]["cpu_pct"]      = crow[0] or 0
                result["metrics"]["cpu_idle_pct"] = crow[1] or 0
            elif result["metrics"] is not None:
                result["metrics"]["cpu_pct"] = 0
        except Exception:
            # Fallback: busca pelo buffer mais recente sem filtro de nó XML
            try:
                cursor.execute("""
                    SELECT TOP 1
                        CONVERT(XML, record).value(
                            '(//ProcessUtilization)[1]', 'int') AS sql_cpu_pct
                    FROM sys.dm_os_ring_buffers WITH (NOLOCK)
                    WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR'
                    ORDER BY timestamp DESC
                """)
                crow2 = cursor.fetchone()
                if crow2 and crow2[0] is not None and result["metrics"] is not None:
                    result["metrics"]["cpu_pct"] = crow2[0] or 0
                elif result["metrics"] is not None:
                    result["metrics"]["cpu_pct"] = 0
            except Exception:
                if result.get("metrics") is not None:
                    result["metrics"]["cpu_pct"] = 0

        # ── Top 10 queries mais caras — filtradas pelo banco monitorado ─────────
        # Como a conexão já aponta para o banco alvo (DATABASE=<target_db> no conn_str),
        # DB_ID() retorna exatamente o ID desse banco. Assim cada agente mostra
        # APENAS as queries do seu próprio contexto de banco.
        cursor.execute("""
            SELECT TOP 10
                qs.total_worker_time / qs.execution_count AS avg_cpu_us,
                qs.total_elapsed_time / qs.execution_count AS avg_elapsed_us,
                qs.total_logical_reads / qs.execution_count AS avg_logical_reads,
                qs.execution_count,
                qs.total_worker_time AS total_cpu_us,
                SUBSTRING(st.text, (qs.statement_start_offset/2)+1,
                    ((CASE qs.statement_end_offset WHEN -1 THEN DATALENGTH(st.text)
                      ELSE qs.statement_end_offset END - qs.statement_start_offset)/2)+1
                ) AS query_text,
                DB_NAME(st.dbid) AS database_name,
                qs.creation_time AS plan_created
            FROM sys.dm_exec_query_stats qs
            CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
            WHERE qs.execution_count > 0
              AND st.dbid = DB_ID()
            ORDER BY qs.total_worker_time / qs.execution_count DESC
            OPTION (MAXDOP 1)
        """)
        for row in cursor.fetchall():
            result["expensive_queries"].append({
                "avg_cpu_ms": round((row[0] or 0) / 1000, 2),
                "avg_elapsed_ms": round((row[1] or 0) / 1000, 2),
                "avg_logical_reads": row[2],
                "execution_count": row[3],
                "total_cpu_ms": round((row[4] or 0) / 1000, 2),
                "query_text": (row[5] or "").strip()[:4000],
                "database_name": row[6],
                "plan_created": str(row[7]),
            })

        # ── Deadlocks recentes (últimas 24h via XE ring buffer) ───────────────
        # Usa cache por instância: a query lê o ring buffer INTEIRO e é cara.
        # Com múltiplos bancos na mesma instância, rodaria N vezes — aqui roda 1×.
        instance_key = (cfg["host"], cfg.get("port", 1433))
        result["deadlocks"] = _get_deadlocks_cached(instance_key, conn)

        if result["deadlocks"]:
            result["alerts"].append({
                "level": "critical",
                "message": f"{len(result['deadlocks'])} deadlock(s) nas últimas 24h",
                "type": "deadlock",
            })

        # ── Sessões ativas bloqueadas ─────────────────────────────────────────
        cursor.execute("""
            SELECT TOP 20
                s.session_id,
                s.login_name,
                s.host_name,
                s.program_name,
                r.command,
                r.status,
                r.wait_type,
                r.wait_time / 1000.0 AS wait_time_sec,
                r.blocking_session_id,
                SUBSTRING(st.text, (r.statement_start_offset/2)+1,
                    ((CASE r.statement_end_offset WHEN -1 THEN DATALENGTH(st.text)
                      ELSE r.statement_end_offset END - r.statement_start_offset)/2)+1
                ) AS current_query
            FROM sys.dm_exec_sessions s
            LEFT JOIN sys.dm_exec_requests r ON r.session_id = s.session_id
            OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) st
            WHERE s.is_user_process = 1
              AND (r.database_id IS NULL OR r.database_id = DB_ID())
            ORDER BY r.wait_time DESC
        """)
        for row in cursor.fetchall():
            result["active_sessions"].append({
                "session_id": row[0],
                "login": row[1],
                "host": row[2],
                "program": row[3],
                "command": row[4],
                "status": row[5],
                "wait_type": row[6],
                "wait_time_sec": float(row[7] or 0),
                "blocking_session_id": row[8],
                "current_query": (row[9] or "").strip()[:500],
            })

        # Busca a última query executada por cada sessão bloqueadora (pode estar idle)
        blocker_ids = list({
            s["blocking_session_id"]
            for s in result["active_sessions"]
            if s["blocking_session_id"]
        })
        blocker_queries = {}
        if blocker_ids:
            placeholders = ",".join(str(i) for i in blocker_ids)
            try:
                cursor.execute(f"""
                    SELECT c.session_id, t.text AS last_query
                    FROM sys.dm_exec_connections c
                    CROSS APPLY sys.dm_exec_sql_text(c.most_recent_sql_handle) t
                    WHERE c.session_id IN ({placeholders})
                """)
                for brow in cursor.fetchall():
                    blocker_queries[brow[0]] = (brow[1] or "").strip()[:1000]
            except Exception:
                pass

        # Enriquece sessões bloqueadas com a query do bloqueador
        for s in result["active_sessions"]:
            if s["blocking_session_id"]:
                s["blocker_query"] = blocker_queries.get(s["blocking_session_id"], "")

        # Apenas bloqueios com wait >= 60s geram alerta
        BLOCKING_MIN_WAIT_SEC = 60
        blocked = [
            s for s in result["active_sessions"]
            if s["blocking_session_id"] and (s.get("wait_time_sec") or 0) >= BLOCKING_MIN_WAIT_SEC
        ]
        if blocked:
            max_wait = max(s.get("wait_time_sec", 0) for s in blocked)
            result["alerts"].append({
                "level": "warning",
                "message": f"{len(blocked)} sessão(ões) bloqueada(s) há {int(max_wait)}s ou mais",
                "type": "blocking",
            })

        # ── Recomendações automáticas (índices faltando via DMV) ─────────────
        try:
            cursor.execute("""
                SELECT TOP 10
                    ROUND(s.avg_total_user_cost * s.avg_user_impact * (s.user_seeks + s.user_scans), 0) AS impact_score,
                    d.statement AS table_name,
                    d.equality_columns,
                    d.inequality_columns,
                    d.included_columns,
                    s.user_seeks,
                    s.user_scans,
                    ROUND(s.avg_user_impact, 0) AS avg_improvement_pct
                FROM sys.dm_db_missing_index_details d
                JOIN sys.dm_db_missing_index_groups g ON d.index_handle = g.index_handle
                JOIN sys.dm_db_missing_index_group_stats s ON g.index_group_handle = s.group_handle
                WHERE d.database_id = DB_ID()
                ORDER BY impact_score DESC
            """)
            recs = []
            for row in cursor.fetchall():
                cols = []
                if row[2]: cols.append(f"= ({row[2]})")
                if row[3]: cols.append(f"< ({row[3]})")
                include = f" INCLUDE ({row[4]})" if row[4] else ""
                recs.append({
                    "impact_score": int(row[0] or 0),
                    "table": (row[1] or "").split(".")[-1],
                    "suggestion": f"CREATE INDEX IX_sugerido ON {row[1]} ({', '.join(cols)}){include}",
                    "user_seeks": int(row[5] or 0),
                    "avg_improvement_pct": int(row[7] or 0),
                    "type": "missing_index",
                })
            if recs:
                result["metrics"]["recommendations"] = recs
        except Exception as rec_err:
            logger.warning(f"[SQLServer] Erro ao coletar recomendações: {rec_err}")

        # ── Último backup por banco ───────────────────────────────────────────
        try:
            cursor.execute("""
                SELECT
                    d.name AS database_name,
                    MAX(b.backup_finish_date) AS last_backup,
                    DATEDIFF(HOUR, MAX(b.backup_finish_date), GETDATE()) AS hours_ago,
                    CAST(MAX(b.backup_size) / 1048576.0 AS DECIMAL(10,1)) AS size_mb
                FROM sys.databases d
                LEFT JOIN msdb.dbo.backupset b
                    ON b.database_name = d.name AND b.type = 'D'
                WHERE d.name NOT IN ('tempdb')
                GROUP BY d.name
                ORDER BY last_backup DESC
            """)
            result["metrics"]["backups"] = [
                {
                    "database_name": r[0],
                    "last_backup": str(r[1]) if r[1] else None,
                    "hours_ago": int(r[2]) if r[2] is not None else None,
                    "size_mb": float(r[3]) if r[3] else None,
                }
                for r in cursor.fetchall()
            ]
            # Alerta se algum banco ficou > 24h sem backup
            sem_backup = [
                b for b in result["metrics"]["backups"]
                if b["hours_ago"] is None or b["hours_ago"] > 24
            ]
            if sem_backup:
                nomes = ", ".join(b["database_name"] for b in sem_backup[:3])
                result["alerts"].append({
                    "level": "warning",
                    "message": f"Backup > 24h ou ausente: {nomes}",
                    "type": "backup",
                })
        except Exception as backup_err:
            logger.warning(f"[SQLServer] Erro ao coletar backups: {backup_err}")

        cursor.close()
        conn.close()

    except Exception as e:
        result["status"] = "offline"
        result["alerts"].append({
            "level": "critical",
            "message": f"Banco inacessível: {str(e)}",
            "type": "offline",
        })
        logger.error(f"[SQLServer] {cfg['name']} erro: {e}")

    return result
