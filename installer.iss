; 28Car 車輛管理系統 - Inno Setup 安裝腳本
; 版本: v1.4
; 日期: 2026-02-13
;
; 使用方式:
;   1. 下載並安裝 Inno Setup: https://jrsoftware.org/isdl.php
;   2. 用 Inno Setup 開啟此檔案
;   3. 點選 Build > Compile (Ctrl+F9)
;   4. 產生的安裝檔會在 Output 資料夾

#define MyAppName "28Car 車輛管理系統"
#define MyAppVersion "1.5"
#define MyAppPublisher "Car2"
#define MyAppURL "http://localhost:5000"
#define MyAppExeName "28car_server.exe"

[Setup]
; 應用程式識別碼
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
; 預設安裝路徑
DefaultDirName=D:\28Car
DefaultGroupName={#MyAppName}
; 允許使用者選擇安裝路徑
AllowNoIcons=yes
; 輸出設定
OutputDir=Output
OutputBaseFilename=28Car_Setup_v{#MyAppVersion}
; 壓縮設定
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
; 需要管理員權限
PrivilegesRequired=admin
; 安裝精靈設定
WizardStyle=modern
; 顯示授權和說明
LicenseFile=
InfoBeforeFile=部署說明.txt
; 解除安裝設定
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
; 使用英文介面（中文語言檔需另外安裝）
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "其他選項:"; Flags: checkedonce
Name: "autostart"; Description: "設定開機自動啟動"; GroupDescription: "其他選項:"; Flags: checkedonce
Name: "schedule"; Description: "設定每日排程任務"; GroupDescription: "其他選項:"; Flags: checkedonce
Name: "firewall"; Description: "設定防火牆規則 (允許區域網路連線)"; GroupDescription: "其他選項:"; Flags: checkedonce

[Files]
; 主程式 EXE
Source: "28car_server.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "28car_scraper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "28car_sms.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "28car_backup.exe"; DestDir: "{app}"; Flags: ignoreversion

; 網頁介面
Source: "index.html"; DestDir: "{app}"; Flags: ignoreversion

; Python 腳本 (備用)
Source: "web_demo.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "scraper_28car.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "sms_sender.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "backup_db.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "run_daily.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "sms_config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; 安裝和工具
Source: "setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "migrate_db.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion

; BAT 腳本
Source: "一鍵部署安裝.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "啟動伺服器.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "檢查伺服器狀態.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "解除安裝.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "設定開機自動啟動.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "檢查更新.bat"; DestDir: "{app}"; Flags: ignoreversion

; 說明文件
Source: "使用說明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "部署說明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "打包說明.txt"; DestDir: "{app}"; Flags: ignoreversion

; 靜態資源
Source: "static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; 資料庫 (重要! 不覆蓋已存在的)
Source: "cars_28car.db"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; Git 版控 (用於遠端更新功能)
Source: ".git\*"; DestDir: "{app}\.git"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".gitignore"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; MinGit (用於遠端更新功能)
Source: "MinGit\*"; DestDir: "{app}\MinGit"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; 建立空的 images 資料夾和 backup 資料夾
Name: "{app}\images"
Name: "{app}\backup"

[Icons]
; 開始功能表
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\開啟網頁"; Filename: "http://localhost:5000"
Name: "{group}\使用說明"; Filename: "{app}\使用說明.txt"
Name: "{group}\解除安裝"; Filename: "{uninstallexe}"

; 桌面捷徑 (exe 內建殺舊進程邏輯)
Name: "{commondesktop}\28Car Server"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{commondesktop}\28Car Web"; Filename: "http://localhost:5000"; Tasks: desktopicon

[Run]
; 安裝完成後執行的動作
; 設定開機自動啟動 (使用 PowerShell 建立捷徑到啟動資料夾)
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -Command ""$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('{userstartup}\28Car Server.lnk'); $s.TargetPath = '{app}\{#MyAppExeName}'; $s.WorkingDirectory = '{app}'; $s.Save()"""; Flags: runhidden; Tasks: autostart

; 設定防火牆
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""28Car Server"" dir=in action=allow protocol=tcp localport=5000"; Flags: runhidden; Tasks: firewall

; 設定排程任務 (備份) - 使用 exe - 半夜 00:00
Filename: "schtasks.exe"; Parameters: "/create /tn ""28car_backup"" /tr ""\""""{app}\28car_backup.exe\"""" /sc daily /st 00:00 /f"; Flags: runhidden; Tasks: schedule

; 設定排程任務 (爬蟲) - 使用 exe - 凌晨 01:00
Filename: "schtasks.exe"; Parameters: "/create /tn ""28car_daily"" /tr ""\""""{app}\28car_scraper.exe\"" --daily --stale-days 14"" /sc daily /st 01:00 /f"; Flags: runhidden; Tasks: schedule

; 設定排程任務 (簡訊) - 使用 exe - 上午 10:00
Filename: "schtasks.exe"; Parameters: "/create /tn ""28car_sms"" /tr ""\""""{app}\28car_sms.exe\"" --daily"" /sc daily /st 10:00 /f"; Flags: runhidden; Tasks: schedule

; 啟動伺服器 (安裝完成後)
Filename: "{app}\{#MyAppExeName}"; Description: "立即啟動 28Car 伺服器"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

; 開啟網頁 (安裝完成後)
Filename: "http://localhost:5000"; Description: "開啟 28Car 網頁"; Flags: postinstall skipifsilent shellexec unchecked

[UninstallRun]
; 解除安裝時移除排程
Filename: "schtasks.exe"; Parameters: "/delete /tn ""28car_backup"" /f"; Flags: runhidden
Filename: "schtasks.exe"; Parameters: "/delete /tn ""28car_daily"" /f"; Flags: runhidden
Filename: "schtasks.exe"; Parameters: "/delete /tn ""28car_sms"" /f"; Flags: runhidden
; 移除防火牆規則
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""28Car Server"""; Flags: runhidden

[UninstallDelete]
; 解除安裝時刪除的檔案 (不刪除資料庫和圖片)
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.pyc"
Type: dirifempty; Name: "{app}\__pycache__"

[Messages]
WelcomeLabel1=歡迎使用 28Car 車輛管理系統
WelcomeLabel2=此程式將安裝 {#MyAppName} v{#MyAppVersion} 到您的電腦。%n%n建議在安裝前關閉所有其他應用程式。%n%n注意：圖片資料夾需另外解壓縮到安裝目錄
FinishedHeadingLabel=安裝完成
FinishedLabel=28Car 車輛管理系統已成功安裝。%n%n預設帳號：admin%n預設密碼：admin%n（首次登入需更改密碼）%n%n後續步驟：%n解壓縮圖片到：{app}\images\%n%n更新功能已整合 MinGit，無需額外安裝 Git。

[Code]
// 安裝前檢查
function InitializeSetup(): Boolean;
begin
  Result := True;
  // 可以在這裡加入檢查邏輯
end;

// 安裝完成後顯示提示
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 安裝完成後的處理
  end;
end;
