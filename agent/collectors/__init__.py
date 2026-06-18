from .sqlserver import collect as collect_sqlserver, discover_databases as discover_sqlserver
from .mysql    import collect as collect_mysql,    discover_databases as discover_mysql


def collect(cfg: dict) -> dict:
    db_type = cfg.get("type", "").lower()
    if db_type == "sqlserver":
        return collect_sqlserver(cfg)
    elif db_type == "mysql":
        return collect_mysql(cfg)
    else:
        raise ValueError(f"Tipo de banco desconhecido: {db_type}")


def discover_databases(instance_cfg: dict) -> list[dict]:
    """Descobre todos os bancos de usuário de uma instância SQL Server ou MySQL."""
    db_type = instance_cfg.get("type", "").lower()
    if db_type == "sqlserver":
        return discover_sqlserver(instance_cfg)
    elif db_type == "mysql":
        return discover_mysql(instance_cfg)
    else:
        raise ValueError(f"Tipo de banco desconhecido: {db_type}")
