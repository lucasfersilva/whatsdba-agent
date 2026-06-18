; ═══════════════════════════════════════════════════════════════
;  WhatsDBA Agent — Inno Setup Installer Script
;  Build: iscc installer.iss
;  Requer: Inno Setup 6+ (https://jrsoftware.org/isdl.php)
;
;  Pré-requisitos:
;    - dist\whatsdba-agent.exe  (gerado pelo PyInstaller)
;    - nssm.exe                 (baixe em https://nssm.cc/release/nssm-2.24.zip)
; ═══════════════════════════════════════════════════════════════

#define MyAppName      "WhatsDBA Agent"
#define MyAppVersion   "1.2.0"
#define MyAppPublisher "InfraCtrl"
#define MyAppURL       "https://whatsdba.infractrl.com.br"
#define MyServiceName  "WhatsDBA-Agent"
#define MyExeName      "whatsdba-agent.exe"

[Setup]
AppId={{A3F8C2D1-5E4B-4A9F-8C3D-2B1E7F6A0D5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\WhatsDBA\Agent
DefaultGroupName=WhatsDBA
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=WhatsDBA-Agent-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSmallImageFile=
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesInstallIn64BitMode=x64

; Ícones e aparência
; WizardImageFile=assets\wizard-banner.bmp
; WizardSmallImageFile=assets\wizard-icon.bmp

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
; Executável principal (PyInstaller output)
Source: "dist\{#MyExeName}";          DestDir: "{app}"; Flags: ignoreversion
; NSSM — gerenciador de serviço Windows
Source: "nssm.exe";                    DestDir: "{app}"; Flags: ignoreversion
; Template de configuração
Source: ".env.example";                DestDir: "{app}"; DestName: ".env.example"; Flags: ignoreversion

[Dirs]
Name: "{app}\logs"; Permissions: everyone-full

[Icons]
Name: "{group}\WhatsDBA Agent — Logs";       Filename: "{app}\logs\agent.log"; WorkingDir: "{app}"
Name: "{group}\WhatsDBA Agent — Configurar"; Filename: "notepad.exe"; Parameters: """{app}\.env"""
Name: "{group}\Desinstalar WhatsDBA Agent";  Filename: "{uninstallexe}"

[Code]
// ── Variáveis globais dos campos do wizard ─────────────────────────────────
var
  PageLicense:    TWizardPage;
  PageDatabase:   TWizardPage;

  // Página de Licença
  edtLicenseKey:  TEdit;
  edtServerURL:   TEdit;
  edtInterval:    TEdit;

  // Página de Banco de Dados
  cmbDbType:      TComboBox;
  edtDbHost:      TEdit;
  edtDbPort:      TEdit;
  edtDbUser:      TEdit;
  edtDbPassword:  TEdit;

// ── Helpers ────────────────────────────────────────────────────────────────
function LabelAbove(Page: TWizardPage; Text: string; Top: Integer): TLabel;
var lbl: TLabel;
begin
  lbl := TLabel.Create(Page);
  lbl.Parent  := Page.Surface;
  lbl.Caption := Text;
  lbl.Top     := Top;
  lbl.Left    := 0;
  lbl.Width   := Page.SurfaceWidth;
  lbl.Font.Style := [fsBold];
  Result := lbl;
end;

function InputBelow(Page: TWizardPage; Top: Integer; Default: string): TEdit;
var ed: TEdit;
begin
  ed := TEdit.Create(Page);
  ed.Parent  := Page.Surface;
  ed.Top     := Top + 18;
  ed.Left    := 0;
  ed.Width   := Page.SurfaceWidth;
  ed.Text    := Default;
  Result := ed;
end;

// ── Cria páginas customizadas ──────────────────────────────────────────────
procedure InitializeWizard();
var
  lbl: TLabel;
begin
  // ── Página 1: Licença e servidor ──────────────────────────────────────
  PageLicense := CreateCustomPage(
    wpWelcome,
    'Configuração da Licença',
    'Informe sua chave de licença WhatsDBA e a URL do servidor.');

  LabelAbove(PageLicense, 'Chave de Licença:', 0);
  edtLicenseKey := InputBelow(PageLicense, 0, 'WDBA-XXXX-XXXX-XXXX');

  LabelAbove(PageLicense, 'URL do Servidor SaaS:', 54);
  edtServerURL := InputBelow(PageLicense, 54, 'https://whatsdba.infractrl.com.br');

  LabelAbove(PageLicense, 'Intervalo de coleta (segundos):', 108);
  edtInterval := InputBelow(PageLicense, 108, '60');

  lbl := TLabel.Create(PageLicense);
  lbl.Parent  := PageLicense.Surface;
  lbl.Caption := 'Não tem uma chave? Adquira em whatsdba.infractrl.com.br';
  lbl.Top     := 168;
  lbl.Left    := 0;
  lbl.Width   := PageLicense.SurfaceWidth;
  lbl.Font.Color := clBlue;

  // ── Página 2: Conexão com banco de dados ──────────────────────────────
  PageDatabase := CreateCustomPage(
    PageLicense.ID,
    'Configuração do Banco de Dados',
    'Informe os dados de conexão com o banco de dados a ser monitorado.');

  LabelAbove(PageDatabase, 'Tipo de Banco:', 0);
  cmbDbType := TComboBox.Create(PageDatabase);
  cmbDbType.Parent := PageDatabase.Surface;
  cmbDbType.Top    := 18;
  cmbDbType.Left   := 0;
  cmbDbType.Width  := 160;
  cmbDbType.Style  := csDropDownList;
  cmbDbType.Items.Add('SQL Server');
  cmbDbType.Items.Add('MySQL');
  cmbDbType.ItemIndex := 0;

  LabelAbove(PageDatabase, 'Host / IP do servidor:', 54);
  edtDbHost := InputBelow(PageDatabase, 54, '127.0.0.1');

  LabelAbove(PageDatabase, 'Porta:', 108);
  edtDbPort := InputBelow(PageDatabase, 108, '1433');
  edtDbPort.Width := 80;

  LabelAbove(PageDatabase, 'Usuário:', 162);
  edtDbUser := InputBelow(PageDatabase, 162, 'sa');

  LabelAbove(PageDatabase, 'Senha:', 216);
  edtDbPassword := InputBelow(PageDatabase, 216, '');
  edtDbPassword.PasswordChar := '*';

  lbl := TLabel.Create(PageDatabase);
  lbl.Parent  := PageDatabase.Surface;
  lbl.Caption := 'O agente descobrirá automaticamente todos os bancos da instância.';
  lbl.Top     := 276;
  lbl.Left    := 0;
  lbl.Width   := PageDatabase.SurfaceWidth;
  lbl.Font.Color := clGray;
end;

// ── Sincroniza porta conforme tipo de banco ────────────────────────────────
procedure CmbDbTypeChange(Sender: TObject);
begin
  if cmbDbType.ItemIndex = 1 then
    edtDbPort.Text := '3306'
  else
    edtDbPort.Text := '1433';
end;

// ── Validações antes de avançar de página ─────────────────────────────────
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = PageLicense.ID then
  begin
    if (Length(Trim(edtLicenseKey.Text)) < 10) or
       (Pos('WDBA-XXXX', edtLicenseKey.Text) > 0) then
    begin
      MsgBox('Informe uma chave de licença válida (ex: WDBA-XXXX-XXXX-XXXX).', mbError, MB_OK);
      Result := False; Exit;
    end;
    if Length(Trim(edtServerURL.Text)) = 0 then
    begin
      MsgBox('Informe a URL do servidor SaaS.', mbError, MB_OK);
      Result := False; Exit;
    end;
  end;

  if CurPageID = PageDatabase.ID then
  begin
    if Length(Trim(edtDbHost.Text)) = 0 then
    begin
      MsgBox('Informe o host / IP do servidor de banco de dados.', mbError, MB_OK);
      Result := False; Exit;
    end;
    if Length(Trim(edtDbUser.Text)) = 0 then
    begin
      MsgBox('Informe o usuário do banco de dados.', mbError, MB_OK);
      Result := False; Exit;
    end;
  end;

end;

// ── Grava o .env e registra o serviço após instalação ─────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile, DbType, DbPort, InstancesJson: string;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // ── Monta INSTANCES JSON ────────────────────────────────────────────
    if cmbDbType.ItemIndex = 1 then
      DbType := 'mysql'
    else
      DbType := 'sqlserver';

    DbPort := Trim(edtDbPort.Text);
    if DbPort = '' then
    begin
      if DbType = 'mysql' then DbPort := '3306' else DbPort := '1433';
    end;

    InstancesJson := Format(
      '[{"type":"%s","host":"%s","port":%s,"user":"%s","password":"%s"}]',
      [DbType,
       Trim(edtDbHost.Text),
       DbPort,
       Trim(edtDbUser.Text),
       Trim(edtDbPassword.Text)]
    );

    // ── Escreve .env ───────────────────────────────────────────────────
    EnvFile :=
      '# WhatsDBA Agent — gerado pelo instalador' + #13#10 +
      'WHATSDBA_LICENSE_KEY=' + Trim(edtLicenseKey.Text) + #13#10 +
      'WHATSDBA_SERVER_URL='  + Trim(edtServerURL.Text)  + #13#10 +
      'COLLECT_INTERVAL='     + Trim(edtInterval.Text)   + #13#10 +
      'INSTANCES=' + InstancesJson + #13#10;

    SaveStringToFile(ExpandConstant('{app}\.env'), EnvFile, False);

    // ── Para e remove serviço anterior ────────────────────────────────
    Exec('sc.exe', 'stop {#MyServiceName}',   '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{app}\nssm.exe'), 'remove {#MyServiceName} confirm',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(2000);

    // ── Registra como Windows Service via NSSM ────────────────────────
    Exec(ExpandConstant('{app}\nssm.exe'),
         'install {#MyServiceName} "' + ExpandConstant('{app}\{#MyExeName}') + '"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} AppDirectory "' + ExpandConstant('{app}') + '"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} DisplayName "WhatsDBA Agent"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} Description "Agente de monitoramento WhatsDBA"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} Start SERVICE_AUTO_START',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} AppStdout "' + ExpandConstant('{app}') + '\logs\agent.log"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} AppStderr "' + ExpandConstant('{app}') + '\logs\agent-error.log"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} AppRotateFiles 1',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} AppRotateBytes 10485760',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    Exec(ExpandConstant('{app}\nssm.exe'),
         'set {#MyServiceName} AppRestartDelay 5000',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // ── Inicia o serviço ───────────────────────────────────────────────
    Exec(ExpandConstant('{app}\nssm.exe'),
         'start {#MyServiceName}',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

// ── Remove o serviço na desinstalação ─────────────────────────────────────
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('sc.exe', 'stop {#MyServiceName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{app}\nssm.exe'), 'remove {#MyServiceName} confirm',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
