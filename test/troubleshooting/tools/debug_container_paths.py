"""
容器路径诊断工具

用�?
    在开发故障测试脚本时,快速探查容器内部的文件路径结构�?
    帮助定位配置文件、日志文件、静态资源等关键路径�?

使用场景:
    1. 编写 generateCase.py/resumeCase.py 时确认文件路�?
    2. 故障构建失败时排查路径问�?
    3. 验证容器内目录结构是否符合预�?

使用方法:
    # 默认检�?ruoyi-app 容器
    python debug_container_paths.py
    
    # 指定容器名称
    python debug_container_paths.py --container mysql
    
    # 查看所有可用选项
    python debug_container_paths.py --help
"""
import sys
import os
import argparse

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from dotenv import load_dotenv
load_dotenv()

import paramiko
from test.troubleshooting.generateCase import execute_ssh_command


def print_section(title):
    """打印分节标题"""
    print("\n" + "="*80)
    print(f"【{title}�?)
    print("="*80)


def check_config_files(container_name):
    """检查配置文件路�?""
    print_section("检查配置文�?)
    
    # 查找 application.yml
    print("\n1️⃣  查找 application.yml 文件:")
    cmd = f"docker exec {container_name} find / -name 'application.yml' 2>/dev/null | grep -v proc | head -10"
    output, error = execute_ssh_command(cmd)
    if output.strip():
        for line in output.strip().split('\n'):
            print(f"   📄 {line}")
    else:
        print("   �?未找�?application.yml")
    
    # 查找所�?application*.yml
    print("\n2️⃣  查找所�?application*.yml 文件:")
    cmd = f"docker exec {container_name} find /app -name 'application*.yml' 2>/dev/null"
    output, error = execute_ssh_command(cmd)
    if output.strip():
        for line in output.strip().split('\n'):
            print(f"   📄 {line}")
    else:
        print("   �?未在 /app 目录下找�?application*.yml")


def check_directory_structure(container_name):
    """检查目录结�?""
    print_section("检查目录结�?)
    
    # 查看 /app 目录
    print("\n1️⃣  /app 目录结构:")
    cmd = f"docker exec {container_name} ls -la /app/ 2>&1"
    output, error = execute_ssh_command(cmd)
    if output.strip() and "No such file" not in output:
        for line in output.strip().split('\n')[:15]:  # 限制显示行数
            print(f"   {line}")
    else:
        print(f"   �?/app 目录不存在或无法访问")
        if error:
            print(f"   错误: {error[:100]}")
    
    # 查看常见子目�?
    subdirs = [
        '/app/ruoyi-admin',
        '/app/ruoyi-admin/src/main/resources',
        '/app/logs',
        '/app/config'
    ]
    
    print("\n2️⃣  检查常见子目录:")
    for subdir in subdirs:
        cmd = f"docker exec {container_name} ls -la {subdir} 2>&1 | head -5"
        output, error = execute_ssh_command(cmd)
        if output.strip() and "No such file" not in output:
            print(f"   �?{subdir} 存在")
        else:
            print(f"   �?{subdir} 不存�?)


def check_log_files(container_name):
    """检查日志文�?""
    print_section("检查日志文�?)
    
    # 查找日志文件
    print("\n1️⃣  查找日志文件:")
    cmd = f"docker exec {container_name} find /app -name '*.log' -o -name 'logs' -type d 2>/dev/null | head -10"
    output, error = execute_ssh_command(cmd)
    if output.strip():
        for line in output.strip().split('\n'):
            print(f"   📝 {line}")
    else:
        print("   �?未找到日志文件或目录")
    
    # 检查常见日志路�?
    print("\n2️⃣  检查常见日志路�?")
    log_paths = [
        '/app/logs',
        '/app/ruoyi-admin/logs',
        '/var/log'
    ]
    
    for log_path in log_paths:
        cmd = f"docker exec {container_name} ls -la {log_path} 2>&1 | head -3"
        output, error = execute_ssh_command(cmd)
        if output.strip() and "No such file" not in output:
            print(f"   �?{log_path}")
            # 显示最近的日志文件
            files = [l for l in output.strip().split('\n')[1:] if l.strip()]
            if files:
                for f in files[:3]:
                    print(f"      {f}")
        else:
            print(f"   �?{log_path} 不存�?)


def check_static_resources(container_name):
    """检查静态资�?""
    print_section("检查静态资�?)
    
    # 查找静态资源目�?
    print("\n1️⃣  查找静态资源目�?")
    cmd = f"docker exec {container_name} find /app -type d -name 'static' 2>/dev/null"
    output, error = execute_ssh_command(cmd)
    if output.strip():
        for line in output.strip().split('\n'):
            print(f"   📁 {line}")
    else:
        print("   �?未找�?static 目录")
    
    # 检�?CSS/JS 文件
    print("\n2️⃣  检�?CSS/JS 文件:")
    cmd = f"docker exec {container_name} find /app -name '*.css' -o -name '*.js' 2>/dev/null | head -10"
    output, error = execute_ssh_command(cmd)
    if output.strip():
        count = len(output.strip().split('\n'))
        print(f"   �?找到 {count} �?CSS/JS 文件")
        for line in output.strip().split('\n')[:5]:
            print(f"      {line}")
        if count > 5:
            print(f"      ... 还有 {count-5} 个文�?)
    else:
        print("   �?未找�?CSS/JS 文件")


def main():
    """主函�?""
    parser = argparse.ArgumentParser(
        description='容器路径诊断工具 - 快速探查容器内部文件路径结�?,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python debug_container_paths.py                      # 检查默认容�?ruoyi-app
  python debug_container_paths.py --container mysql    # 检�?MySQL 容器
  python debug_container_paths.py -c ruoyi-app --section config  # 仅检查配�?
        """
    )
    
    parser.add_argument(
        '-c', '--container',
        type=str,
        default='ruoyi-app',
        help='容器名称 (默认: ruoyi-app)'
    )
    
    parser.add_argument(
        '-s', '--section',
        type=str,
        choices=['config', 'directory', 'logs', 'static', 'all'],
        default='all',
        help='检查部�? config/directory/logs/static/all (默认: all)'
    )
    
    args = parser.parse_args()
    
    container_name = args.container
    section = args.section
    
    print("\n" + "="*80)
    print("🔍 容器路径诊断工具")
    print("="*80)
    print(f"📦 容器名称: {container_name}")
    print(f"📋 检查范�? {section}")
    print("="*80)
    
    # 检查容器是否运�?
    print("\n⚙️  检查容器状�?..")
    cmd = f"docker ps | grep {container_name}"
    output, error = execute_ssh_command(cmd)
    
    if container_name not in output:
        print(f"�?错误: 容器 '{container_name}' 未运�?)
        print("💡 请先启动容器或使�?'docker ps' 查看可用容器")
        return
    
    print(f"�?容器 '{container_name}' 运行�?)
    
    # 根据选择执行检�?
    if section in ['config', 'all']:
        check_config_files(container_name)
    
    if section in ['directory', 'all']:
        check_directory_structure(container_name)
    
    if section in ['logs', 'all']:
        check_log_files(container_name)
    
    if section in ['static', 'all']:
        check_static_resources(container_name)
    
    # 总结
    print("\n" + "="*80)
    print("�?诊断完成!")
    print("="*80)
    print("\n💡 下一�?")
    print("   1. 将找到的路径应用�?generateCase.py / resumeCase.py")
    print("   2. 如需检查其他容�? python debug_container_paths.py -c <容器�?")
    print()


if __name__ == "__main__":
    main()
