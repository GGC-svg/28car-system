#!/usr/bin/env python3
"""
setup.py -- 28Car 一鍵部署安裝腳本
====================================
功能：
  1. 建立桌面捷徑
  2. 設定開機自動啟動
  3. 設定每日排程任務
  4. 設定防火牆規則
  5. 啟動伺服器

使用方式：
  python setup.py              # 完整安裝
  python setup.py --uninstall  # 移除安裝
"""

import os
import sys
import ctypes
import subprocess
import socket

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def is_admin():
    """檢查是否有管理員權限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """以管理員身分重新執行"""
    if sys.platform == 'win32':
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{__file__}"', None, 1
        )
        sys.exit(0)


def get_local_ip():
    """取得本機 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "未知"


def create_shortcut(target, shortcut_path, working_dir=None, description=""):
    """建立桌面捷徑"""
    try:
        # 使用 PowerShell 建立捷徑（最可靠的方式）
        ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{target}"
'''
        if working_dir:
            ps_script += f'$Shortcut.WorkingDirectory = "{working_dir}"\n'
        ps_script += '$Shortcut.Save()'

        result = subprocess.run(
            ['powershell', '-Command', ps_script],
            capture_output=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  建立捷徑失敗: {e}")
        return False


def setup_desktop_shortcuts():
    """建立桌面捷徑"""
    print("\n步驟 1/5: 建立桌面捷徑")
    print("-" * 40)

    desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')

    # 判斷是 exe 還是 python 版本
    server_exe = os.path.join(BASE_DIR, '28car_server.exe')
    if os.path.exists(server_exe):
        server_target = server_exe
    else:
        server_target = os.path.join(BASE_DIR, 'web_demo.py')

    # 伺服器捷徑
    shortcut1 = os.path.join(desktop, '28Car Server.lnk')
    if create_shortcut(server_target, shortcut1, BASE_DIR, '28Car 車輛管理系統'):
        print("  [OK] 28Car Server.lnk")
    else:
        print("  [!] 28Car Server.lnk 建立失敗")

    # 網頁捷徑
    shortcut2 = os.path.join(desktop, '28Car Web.lnk')
    if create_shortcut('http://localhost:5000', shortcut2, description='開啟 28Car 網頁'):
        print("  [OK] 28Car Web.lnk")
    else:
        print("  [!] 28Car Web.lnk 建立失敗")


def setup_autostart():
    """設定開機自動啟動"""
    print("\n步驟 2/5: 設定開機自動啟動")
    print("-" * 40)

    startup_folder = os.path.join(
        os.environ['APPDATA'],
        'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup'
    )

    server_exe = os.path.join(BASE_DIR, '28car_server.exe')
    if os.path.exists(server_exe):
        target = server_exe
    else:
        target = os.path.join(BASE_DIR, 'web_demo.py')

    shortcut_path = os.path.join(startup_folder, '28Car Server.lnk')
    if create_shortcut(target, shortcut_path, BASE_DIR, '28Car 開機啟動'):
        print("  [OK] 開機自動啟動已設定")
    else:
        print("  [!] 開機自動啟動設定失敗")


def setup_scheduled_tasks():
    """設定排程任務"""
    print("\n步驟 3/5: 設定每日排程任務")
    print("-" * 40)

    # 判斷是 exe 版本還是 python 版本
    is_exe = os.path.exists(os.path.join(BASE_DIR, '28car_scraper.exe'))

    if is_exe:
        # EXE 版本 - 直接執行 exe
        tasks = [
            ('28car_backup', '00:00', os.path.join(BASE_DIR, '28car_backup.exe'), '每日備份', 'exe'),
            ('28car_daily', '01:00', os.path.join(BASE_DIR, '28car_scraper.exe') + '" --daily', '每日爬蟲', 'exe_args'),
            ('28car_sms', '10:00', os.path.join(BASE_DIR, '28car_sms.exe') + '" --daily', '每日簡訊', 'exe_args'),
        ]
    else:
        # Python 版本
        tasks = [
            ('28car_backup', '00:00', os.path.join(BASE_DIR, 'backup_db.py'), '每日備份', 'py'),
            ('28car_daily', '01:00', os.path.join(BASE_DIR, 'scraper_28car.py') + '" --daily', '每日爬蟲', 'py_args'),
            ('28car_sms', '10:00', os.path.join(BASE_DIR, 'sms_sender.py') + '" --daily', '每日簡訊', 'py_args'),
        ]

    for task_name, time, script, desc, script_type in tasks:
        # 刪除舊排程
        subprocess.run(
            ['schtasks', '/delete', '/tn', task_name, '/f'],
            capture_output=True
        )

        # 根據類型建立執行命令
        if script_type == 'exe':
            tr = f'"{script}"'
        elif script_type == 'exe_args':
            # 格式: path.exe" --args
            script_path = script.split('" ')[0]
            args = script.split('" ')[1] if '" ' in script else ''
            tr = f'"{script_path}" {args}'
        elif script_type == 'py':
            tr = f'"{sys.executable}" "{script}"'
        elif script_type == 'py_args':
            # 格式: path.py" --args
            script_path = script.split('" ')[0]
            args = script.split('" ')[1] if '" ' in script else ''
            tr = f'"{sys.executable}" "{script_path}" {args}'
        elif script_type == 'bat':
            tr = f'"{script}"'
        elif script_type == 'cmd':
            tr = f'cmd /c "cd /d "{BASE_DIR}" && {script}"'
        else:
            tr = f'"{script}"'

        # 建立新排程
        # 28car_daily 改為週一到週五，其他維持每天
        if task_name == '28car_daily':
            result = subprocess.run(
                ['schtasks', '/create', '/tn', task_name, '/tr', tr,
                 '/sc', 'weekly', '/d', 'MON,TUE,WED,THU,FRI', '/st', time, '/f'],
                capture_output=True
            )
        else:
            result = subprocess.run(
                ['schtasks', '/create', '/tn', task_name, '/tr', tr,
                 '/sc', 'daily', '/st', time, '/f'],
                capture_output=True
            )

        if result.returncode == 0:
            print(f"  [OK] {desc} ({task_name}) - 每日 {time}")
        else:
            print(f"  [!] {desc} 設定失敗（需要管理員權限）")

    # 週六全量掃描排程
    subprocess.run(['schtasks', '/delete', '/tn', '28car_weekly', '/f'], capture_output=True)
    if is_exe:
        weekly_tr = f'"{os.path.join(BASE_DIR, "28car_scraper.exe")}" --stale-days 7'
    else:
        weekly_tr = f'"{sys.executable}" "{os.path.join(BASE_DIR, "scraper_28car.py")}" --stale-days 7'
    result = subprocess.run(
        ['schtasks', '/create', '/tn', '28car_weekly', '/tr', weekly_tr,
         '/sc', 'weekly', '/d', 'SAT', '/st', '02:00', '/f'],
        capture_output=True
    )
    if result.returncode == 0:
        print(f"  [OK] 週六全量掃描 (28car_weekly) - 每週六 02:00")
    else:
        print(f"  [!] 週六全量掃描設定失敗（需要管理員權限）")


def setup_firewall():
    """設定防火牆"""
    print("\n步驟 4/5: 設定防火牆")
    print("-" * 40)

    # 刪除舊規則
    subprocess.run(
        ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', 'name=28Car Server'],
        capture_output=True
    )

    # 新增規則
    result = subprocess.run(
        ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
         'name=28Car Server', 'dir=in', 'action=allow',
         'protocol=tcp', 'localport=5000'],
        capture_output=True
    )

    if result.returncode == 0:
        print("  [OK] 防火牆規則已設定（TCP 5000）")
    else:
        print("  [!] 防火牆設定失敗（需要管理員權限）")


def start_server():
    """啟動伺服器"""
    print("\n步驟 5/5: 啟動伺服器")
    print("-" * 40)

    # 檢查是否已在執行
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 5000))
    sock.close()

    if result == 0:
        print("  [OK] 伺服器已在執行中")
        return

    server_exe = os.path.join(BASE_DIR, '28car_server.exe')
    if os.path.exists(server_exe):
        subprocess.Popen([server_exe], cwd=BASE_DIR)
    else:
        subprocess.Popen([sys.executable, os.path.join(BASE_DIR, 'web_demo.py')], cwd=BASE_DIR)

    print("  [OK] 伺服器已啟動")


def show_summary():
    """顯示安裝摘要"""
    local_ip = get_local_ip()

    print("\n")
    print("=" * 50)
    print("  安裝完成！")
    print("=" * 50)
    print("")
    print("  桌面已新增:")
    print("    - 28Car Server（啟動伺服器）")
    print("    - 28Car Web（開啟網頁）")
    print("")
    print("  自動化設定:")
    print("    - 開機自動啟動伺服器")
    print("    - 每天 05:00 執行資料庫備份")
    print("    - 每天 06:00 執行爬蟲更新")
    print("    - 每天 10:00 執行簡訊發送（依設定時間區間）")
    print("")
    print("  連線網址:")
    print(f"    本機: http://localhost:5000")
    print(f"    區網: http://{local_ip}:5000")
    print("")
    print("  預設帳號: admin / admin")
    print("  （首次登入需更改密碼）")
    print("")
    print("=" * 50)


def uninstall():
    """移除安裝"""
    print("移除 28Car 安裝...")

    # 移除排程
    for task in ['28car_daily', '28car_weekly', '28car_sms', '28car_backup']:
        subprocess.run(['schtasks', '/delete', '/tn', task, '/f'], capture_output=True)
        print(f"  已移除排程: {task}")

    # 移除防火牆規則
    subprocess.run(
        ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', 'name=28Car Server'],
        capture_output=True
    )
    print("  已移除防火牆規則")

    # 移除捷徑
    desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
    for f in ['28Car Server.lnk', '28Car Web.lnk']:
        try:
            os.remove(os.path.join(desktop, f))
            print(f"  已移除桌面捷徑: {f}")
        except:
            pass

    # 移除開機啟動
    startup_folder = os.path.join(
        os.environ['APPDATA'],
        'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup'
    )
    try:
        os.remove(os.path.join(startup_folder, '28Car Server.lnk'))
        print("  已移除開機啟動")
    except:
        pass

    print("\n移除完成！")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='28Car 一鍵部署安裝')
    parser.add_argument('--uninstall', action='store_true', help='移除安裝')
    args = parser.parse_args()

    print("=" * 50)
    print("  28Car 車輛管理系統 - 一鍵部署安裝")
    print("=" * 50)

    # 檢查管理員權限
    if not is_admin():
        print("\n需要管理員權限，正在請求...")
        run_as_admin()
        return

    print("\n[OK] 已取得管理員權限")
    print(f"安裝路徑: {BASE_DIR}")

    if args.uninstall:
        uninstall()
        input("\n按 Enter 關閉...")
        return

    # 執行安裝
    setup_desktop_shortcuts()
    setup_autostart()
    setup_scheduled_tasks()
    setup_firewall()
    start_server()
    show_summary()

    input("\n按 Enter 關閉...")


if __name__ == '__main__':
    main()
