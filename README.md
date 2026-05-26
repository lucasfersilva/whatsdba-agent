# WhatsDBA Agent

Agente de monitoramento do [WhatsDBA](https://whatsdba.infractrl.com.br) — instale no servidor SQL e receba alertas automáticos via WhatsApp sobre bloqueios, deadlocks, slow queries e disponibilidade.

## Requisitos

| Item | Versão mínima |
|------|---------------|
| Python | 3.9+ |
| SQL Server | 2014+ (requer ODBC Driver 17) |
| MySQL | 5.7+ / 8.0+ |
| OS | Windows Server 2016+ · Ubuntu 20.04+ · Debian 11+ · RHEL/CentOS 8+ |

> **Chave de licença obrigatória.** Obtenha a sua em [whatsdba.infractrl.com.br](https://whatsdba.infractrl.com.br).

---

## Instalação rápida

### 🪟 Windows (PowerShell como Administrador)

```powershell
# 1. Clone ou baixe o agente
git clone https://github.com/infractrl/whatsdba-agent.git
cd whatsdba-agent

# 2. Configure o .env
copy .env.example .env
notepad .env

# 3. Instale como serviço Windows
.\install-windows.ps1
```

### 🐧 Linux (Ubuntu / Debian / RHEL / CentOS)

```bash
# 1. Clone ou baixe o agente
git clone https://github.com/infractrl/whatsdba-agent.git
cd whatsdba-agent

# 2. Configure o .env
cp .env.example .env
nano .env

# 3. Instale como serviço systemd
sudo bash install-linux.sh
```

---

## Configuração (.env)

O arquivo `.env` precisa de três informações principais:

```env
WHATSDBA_LICENSE_KEY=WDBA-XXXX-XXXX-XXXX
WHATSDBA_SERVER_URL=https://whatsdba.infractrl.com.br
COLLECT_INTERVAL=60
```

### Configurando instâncias (modo recomendado)

Informe apenas as **credenciais de conexão** — o agente descobre todos os bancos automaticamente:

```env
# SQL Server
INSTANCES=[{"type":"sqlserver","host":"127.0.0.1","port":1433,"user":"sa","password":"SENHA"}]

# MySQL
INSTANCES=[{"type":"mysql","host":"127.0.0.1","port":3306,"user":"root","password":"SENHA"}]

# Múltiplas instâncias
INSTANCES=[
  {"type":"sqlserver","host":"10.0.0.1","user":"sa","password":"SENHA1","label":"SQL-PROD"},
  {"type":"mysql","host":"10.0.0.2","user":"root","password":"SENHA2","label":"MYSQL-PROD"}
]
```

### Filtrando bancos (opcional)

```env
# Monitorar todos, exceto bancos de teste
INSTANCES=[{"type":"sqlserver","host":"10.0.0.1","user":"sa","password":"SENHA",
            "exclude_databases":["Teste","Homologacao","Dev"]}]

# Monitorar somente bancos específicos
INSTANCES=[{"type":"sqlserver","host":"10.0.0.1","user":"sa","password":"SENHA",
            "include_databases":["Producao","Financeiro","RH"]}]
```

---

## Comandos úteis

### Windows

```powershell
# Status do serviço
Get-Service WhatsDBA-Agent

# Ver logs em tempo real
Get-Content .\logs\agent.log -Wait -Tail 50

# Reiniciar
Restart-Service WhatsDBA-Agent

# Parar
Stop-Service WhatsDBA-Agent
```

### Linux

```bash
# Status
sudo systemctl status whatsdba-agent

# Logs em tempo real
sudo journalctl -u whatsdba-agent -f

# Reiniciar
sudo systemctl restart whatsdba-agent

# Parar
sudo systemctl stop whatsdba-agent
```

---

## SQL Server — permissões mínimas

O usuário de monitoramento não precisa ser `sa`. Crie um usuário com permissões mínimas:

```sql
-- Cria usuário de monitoramento
CREATE LOGIN whatsdba_monitor WITH PASSWORD = 'SenhaForte123!';
CREATE USER  whatsdba_monitor FOR LOGIN whatsdba_monitor;

-- Permissões de leitura de DMVs (necessário para métricas)
GRANT VIEW SERVER STATE TO whatsdba_monitor;
GRANT VIEW ANY DATABASE  TO whatsdba_monitor;

-- Acesso a cada banco monitorado
USE [SeuBanco];
CREATE USER whatsdba_monitor FOR LOGIN whatsdba_monitor;
GRANT SELECT ON SCHEMA::dbo TO whatsdba_monitor;
```

---

## MySQL — permissões mínimas

```sql
CREATE USER 'whatsdba_monitor'@'%' IDENTIFIED BY 'SenhaForte123!';
GRANT PROCESS, REPLICATION CLIENT ON *.* TO 'whatsdba_monitor'@'%';
GRANT SELECT ON performance_schema.* TO 'whatsdba_monitor'@'%';
FLUSH PRIVILEGES;
```

---

## Instalando ODBC Driver (SQL Server no Linux)

```bash
# Ubuntu / Debian
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list \
  | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev

# RHEL / CentOS 8+
curl https://packages.microsoft.com/config/rhel/8/prod.repo \
  | sudo tee /etc/yum.repos.d/mssql-release.repo
sudo ACCEPT_EULA=Y dnf install -y msodbcsql17
```

---

## Solução de problemas

**Agente não aparece no dashboard após instalação**
- Verifique se `WHATSDBA_LICENSE_KEY` está correto
- Confirme que o servidor tem acesso à internet para `whatsdba.infractrl.com.br`
- Veja os logs: `journalctl -u whatsdba-agent -n 50` (Linux) ou `logs\agent-error.log` (Windows)

**Nenhum banco descoberto**
- Confirme que o usuário SQL tem permissão `VIEW SERVER STATE` (SQL Server) ou `PROCESS` (MySQL)
- Teste a conexão manualmente com as mesmas credenciais do `.env`

**ODBC Driver não encontrado (Linux)**
- Siga as instruções da seção "Instalando ODBC Driver" acima
- Reinicie o agente após instalar: `sudo systemctl restart whatsdba-agent`

---

## Suporte

- 📧 suporte@infractrl.com.br
- 🌐 [whatsdba.infractrl.com.br](https://whatsdba.infractrl.com.br)
