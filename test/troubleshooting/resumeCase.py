"""
统一恢复所有故障测试环�?
支持通过命令行参数或交互式选择要恢复的case
"""
import sys
import os
import argparse
import time

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import paramiko
from dotenv import load_dotenv
load_dotenv()

# SSH配置
ssh_config = {
    "host": os.getenv("SSH_HOST"),
    "port": int(os.getenv("SSH_PORT", "22")),
    "username": os.getenv("SSH_USER"),
    "key_file": os.getenv("SSH_KEY_PATH", "./aiOps.pem")
}

# 如果是相对路�?转换为绝对路�?
if not os.path.isabs(ssh_config["key_file"]):
    ssh_config["key_file"] = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ssh_config["key_file"])


def execute_ssh_command(cmd, timeout=30):
    """
    执行SSH命令
    
    Args:
        cmd: 要执行的命令
        timeout: 超时时间(�?
    
    Returns:
        tuple: (stdout输出, stderr输出)
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=ssh_config["key_file"],
            timeout=timeout
        )
        
        stdin, stdout, stderr = ssh.exec_command(cmd)
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        return output, error
    except Exception as e:
        print(f"�?SSH命令执行失败: {str(e)}")
        return "", str(e)
    finally:
        ssh.close()


def resume_case01():
    """
    Case01: 恢复Tomcat线程池配�?
    
    恢复步骤:
    1. 删除外部配置文件
    2. 停止并重新创建容�?不挂载配置文�?
    3. 验证服务恢复正常响应速度
    """
    print("\n" + "="*80)
    print("【Case01】恢复Tomcat线程池配�?)
    print("="*80)
    
    container_name = "ruoyi-app"
    host_config_dir = "/opt/services/ruoyi/config"
    
    # 步骤1: 删除外部配置文件
    print("\n1️⃣  删除外部配置文件...")
    remove_cmd = f"sudo rm -f {host_config_dir}/application.yml"
    execute_ssh_command(remove_cmd)
    print("   �?配置文件已删�?)
    
    # 步骤2: 停止当前容器
    print("\n2️⃣  停止ruoyi-app容器...")
    stop_cmd = f"docker stop {container_name}"
    execute_ssh_command(stop_cmd)
    print("   �?容器已停�?)
    
    # 步骤3: 删除旧容�?
    print("\n3️⃣  删除旧容�?..")
    rm_cmd = f"docker rm {container_name}"
    execute_ssh_command(rm_cmd)
    print("   �?容器已删�?)
    
    # 步骤4: 重新启动容器(不挂载配置文�?
    print("\n4️⃣  重新启动容器(使用默认配置)...")
    restart_cmd = f"""docker run -d \
  --name {container_name} \
  --restart always \
  -p 8080:80 \
  -e TZ=Asia/Shanghai \
  -e SPRING_DATASOURCE_DRUID_MASTER_URL=jdbc:mysql://mysql:3306/ry?useUnicode=true&characterEncoding=utf8&zeroDateTimeBehavior=convertToNull&useSSL=true&serverTimezone=GMT%2B8 \
  -e SPRING_DATASOURCE_DRUID_MASTER_USERNAME=root \
  -e SPRING_DATASOURCE_DRUID_MASTER_PASSWORD='.My19w2fLC6Ob' \
  -e SPRING_REDIS_HOST=redis \
  -e SPRING_REDIS_PORT=6379 \
  -e SPRING_REDIS_PASSWORD='.My19w2fLC6Ob' \
  -v /opt/services/ruoyi/logs:/app/logs \
  -v /opt/services/ruoyi/upload:/app/profile \
  --memory=1G \
  --cpus=2.0 \
  --network services_services-network \
  ruoyi-app:latest"""
    
    output, error = execute_ssh_command(restart_cmd)
    
    if error and "Error" in error:
        print(f"   ⚠️  启动警告: {error}")
    else:
        print("   �?容器已启�?)
    
    # 步骤5: 等待容器启动
    print("\n5️⃣  等待容器启动(�?0�?...")
    for i in range(30, 0, -5):
        print(f"   �?剩余 {i} �?..", end='\r')
        time.sleep(5)
    print("   �?容器启动完成")
    
    # 步骤6: 验证服务恢复正常
    print("\n6️⃣  验证服务恢复正常...")
    health_check_cmd = "curl -s -o /dev/null -w '%{http_code}' http://localhost:80/login"
    http_code, _ = execute_ssh_command(health_check_cmd)
    
    if http_code.strip() == "200":
        print("   �?服务恢复正常! HTTP状态码: 200")
    elif http_code.strip():
        print(f"   ⚠️  服务状态码: {http_code.strip()},可能需要更多时间启�?)
    else:
        print("   �?无法访问服务,请检查容器状�?)
    
    # 步骤7: 清理临时文件
    print("\n7️⃣  清理临时文件...")
    cleanup_cmd = f"sudo rm -rf {host_config_dir}"
    execute_ssh_command(cleanup_cmd)
    print("   �?清理完成")
    
    print("\n" + "="*80)
    print("【Case01】环境恢复完�?")
    print("="*80)
    print("\n💡 验证建议:")
    print("   1. 访问前端页面确认功能正常")
    print("   2. 测试高并发下的响应时间是否恢复正�?)
    print("   3. 检查容器日志无异常: docker logs ruoyi-app --tail 50")
    print()


def resume_case03():
    """
    Case03: 恢复MySQL连接池配�?
    
    恢复步骤:
    1. 恢复备份的配置文�?
    2. 重启容器
    3. 验证服务恢复正常
    """
    print("\n" + "="*80)
    print("【Case03】恢复MySQL连接池配�?)
    print("="*80)
    
    container_name = "ruoyi-app"
    config_file = "/app/ruoyi-admin/src/main/resources/application-druid.yml"
    
    # 步骤1: 恢复配置文件
    print("\n1️⃣  恢复原始配置文件...")
    restore_cmd = f"docker exec {container_name} sh -c 'if [ -f {config_file}.bak ]; then mv {config_file}.bak {config_file}; else echo \"Backup not found\"; fi'"
    output, error = execute_ssh_command(restore_cmd)
    
    if "Backup not found" in output:
        print("   ⚠️  未找到备份文�?可能需要手动恢复配�?)
        print("   💡 建议检查容器内是否有备�? docker exec ruoyi-app ls -la /app/ruoyi-admin/src/main/resources/")
    else:
        print("   �?配置文件已恢�?)
    
    # 步骤2: 重启容器
    print("\n2️⃣  重启ruoyi-app容器...")
    restart_cmd = f"docker restart {container_name}"
    execute_ssh_command(restart_cmd)
    
    # 步骤3: 等待容器启动
    print("\n3️⃣  等待容器启动(�?0�?...")
    for i in range(60, 0, -5):
        print(f"   �?剩余 {i} �?..", end='\r')
        time.sleep(5)
    print("   �?容器启动完成")
    
    # 步骤4: 验证服务恢复正常
    print("\n4️⃣  验证服务恢复正常...")
    health_check_cmd = "curl -s -o /dev/null -w '%{http_code}' http://localhost:80/login"
    http_code, _ = execute_ssh_command(health_check_cmd)
    
    if http_code.strip() == "200":
        print("   �?服务恢复正常! HTTP状态码: 200")
    elif http_code.strip():
        print(f"   ⚠️  服务状态码: {http_code.strip()},可能需要更多时间启�?)
    else:
        print("   �?无法访问服务,请检查容器状�?)
    
    # 步骤5: 验证连接池配置已恢复
    print("\n5️⃣  验证连接池配�?..")
    check_config_cmd = f"docker exec {container_name} grep -A 2 'maxActive:' {config_file}"
    config_output, _ = execute_ssh_command(check_config_cmd)
    
    if "maxActive: 20" in config_output or "maxActive:20" in config_output:
        print("   �?连接池配置已恢复为正常�?maxActive=20)")
    else:
        print("   ⚠️  配置可能未正确恢�?当前配置:")
        print(f"      {config_output.strip()}")
    
    # 步骤6: 清理临时文件
    print("\n6️⃣  清理临时文件...")
    cleanup_cmd = f"docker exec {container_name} rm -f {config_file}.bak"
    execute_ssh_command(cleanup_cmd)
    print("   �?清理完成")
    
    print("\n" + "="*80)
    print("【Case03】环境恢复完�?")
    print("="*80)
    print("\n💡 验证建议:")
    print("   1. 访问前端页面确认功能正常")
    print("   2. 检查容器日志无异常: docker logs ruoyi-app --tail 50")
    print("   3. 监控系统资源使用情况")
    print()


def resume_case02():
    """
    Case02: 恢复静态资�?
    
    恢复步骤:
    1. 恢复备份的静态资源目�?
    2. 验证文件已恢�?
    3. 清理备份
    """
    print("\n" + "="*80)
    print("【Case02】恢复静态资�?)
    print("="*80)
    
    container_name = "ruoyi-app"
    static_dir = "/app/ruoyi-admin/src/main/resources/static"
    
    # 步骤1: 恢复静态资源目�?
    print("\n1️⃣  恢复静态资源目�?..")
    restore_cmd = f"docker exec {container_name} sh -c 'if [ -d {static_dir}.bak ]; then rm -rf {static_dir} && mv {static_dir}.bak {static_dir}; else echo \"Backup not found\"; fi'"
    output, error = execute_ssh_command(restore_cmd)
    
    if "Backup not found" in output:
        print("   ⚠️  未找到备份目�?可能需要重新部署应�?)
        print(f"   💡 建议检�? docker exec {container_name} ls -la /app/ruoyi-admin/src/main/resources/")
    else:
        print("   �?静态资源目录已恢复")
    
    # 步骤2: 验证文件已恢�?
    print("\n2️⃣  验证文件恢复情况...")
    check_css_cmd = f"docker exec {container_name} ls {static_dir}/css/*.css 2>&1 | head -3"
    css_output, _ = execute_ssh_command(check_css_cmd)
    
    if css_output.strip() and "No such file" not in css_output:
        print("   �?CSS文件已恢�?)
        print(f"      示例: {css_output.strip().split(chr(10))[0]}")
    else:
        print("   ⚠️  CSS文件可能未完全恢�?)
    
    # 步骤3: 清理备份
    print("\n3️⃣  清理备份目录...")
    cleanup_cmd = f"docker exec {container_name} rm -rf {static_dir}.bak"
    execute_ssh_command(cleanup_cmd)
    print("   �?清理完成")
    
    print("\n" + "="*80)
    print("【Case02】环境恢复完�?")
    print("="*80)
    print("\n💡 验证建议:")
    print("   1. 刷新浏览器页�?Ctrl+F5强制刷新)")
    print("   2. 检查浏览器控制台Network标签,确认�?04错误")
    print("   3. 验证页面样式和交互功能正�?)
    print()


def resume_case05():
    """
    Case05: 恢复MySQL慢查询环�?
    
    恢复步骤:
    1. 终止慢查询进�?
    2. 删除测试�?
    3. 验证CPU使用率恢复正�?
    4. 清理测试数据
    """
    print("\n" + "="*80)
    print("【Case05】恢复MySQL慢查询环�?)
    print("="*80)
    
    mysql_container = "mysql"
    db_user = "root"
    db_password = ".My19w2fLC6Ob"
    db_name = "ry"
    
    # 步骤1: 终止慢查询进�?
    print("\n1️⃣  终止慢查询进�?..")
    kill_cmd = f"docker exec {mysql_container} pkill -f 'SELECT t1.*' || true"
    execute_ssh_command(kill_cmd)
    print("   �?慢查询进程已终止")
    
    # 步骤2: 删除测试�?
    print("\n2️⃣  删除测试�?..")
    drop_sql = "DROP TABLE IF EXISTS test_slow_query;"
    drop_cmd = f"docker exec {mysql_container} mysql -u{db_user} -p'{db_password}' {db_name} -e \"{drop_sql}\""
    output, error = execute_ssh_command(drop_cmd)
    
    if error and "ERROR" in error:
        print(f"   ⚠️  删除表警�? {error[:100]}")
    else:
        print("   �?测试表已删除")
    
    # 步骤3: 验证CPU使用�?
    print("\n3️⃣  检查CPU使用�?..")
    time.sleep(5)  # 等待几秒让CPU降下�?
    
    cpu_check_cmd = "top -bn1 | grep -i mysql | head -3"
    cpu_output, _ = execute_ssh_command(cpu_check_cmd)
    
    if cpu_output.strip():
        print("   📊 MySQL进程CPU使用情况:")
        for line in cpu_output.strip().split('\n')[:3]:
            print(f"      {line[:100]}")
    else:
        print("   ℹ️  未检测到MySQL进程或CPU已恢复正�?)
    
    # 步骤4: 清理可能残留的进�?
    print("\n4️⃣  清理残留进程...")
    cleanup_cmd = f"docker exec {mysql_container} pkill -9 -f 'nohup mysql' || true"
    execute_ssh_command(cleanup_cmd)
    print("   �?清理完成")
    
    print("\n" + "="*80)
    print("【Case05】环境恢复完�?")
    print("="*80)
    print("\n💡 验证建议:")
    print("   1. 监控系统CPU使用率是否恢复正�?)
    print("   2. 检查MySQL进程列表: docker exec mysql mysql -uroot -p'.My19w2fLC6Ob' -e 'SHOW PROCESSLIST;'")
    print("   3. 确认无长时间运行的查�?)
    print()


def resume_case03():
    """Case03: 恢复Docker容器OOM环境"""
    print("\n" + "="*80)
    print("【Case03】恢复Docker容器OOM环境")
    print("="*80)
    print("\n⚠️  此场景暂未实�?敬请期待...")
    print()


def resume_case04():
    """
    Case04: 恢复JVM堆内存配�?
    
    恢复步骤:
    1. 恢复备份的docker-compose配置
    2. 重启容器
    3. 清理Heap Dump文件
    4. 验证服务恢复正常
    """
    print("\n" + "="*80)
    print("【Case04】恢复JVM堆内存配�?)
    print("="*80)
    
    container_name = "ruoyi-app"
    compose_file = "/opt/source/RuoYi/docker-compose.ruoyi.yml"
    
    # 步骤1: 恢复配置文件
    print("\n1️⃣  恢复原始docker-compose配置...")
    restore_cmd = f"mv {compose_file}.bak {compose_file}"
    output, error = execute_ssh_command(restore_cmd)
    
    if error or "No such file" in output:
        print("   ⚠️  未找到备份文�?可能需要手动恢复配�?)
        print(f"   💡 建议检�? ls -la /opt/source/RuoYi/")
    else:
        print("   �?配置文件已恢�?)
    
    # 步骤2: 重启容器
    print("\n2️⃣  重启ruoyi-app容器...")
    restart_cmd = f"cd /opt/source/RuoYi/ && docker-compose -f docker-compose.ruoyi.yml up -d"
    execute_ssh_command(restart_cmd)
    
    # 步骤3: 等待容器启动
    print("\n3️⃣  等待容器启动(�?0�?...")
    for i in range(60, 0, -5):
        print(f"   �?剩余 {i} �?..", end='\r')
        time.sleep(5)
    print("   �?容器启动完成")
    
    # 步骤4: 验证服务恢复正常
    print("\n4️⃣  验证服务恢复正常...")
    health_check_cmd = "curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/login"
    http_code, _ = execute_ssh_command(health_check_cmd)
    
    if http_code.strip() == "200":
        print("   �?服务恢复正常! HTTP状态码: 200")
    elif http_code.strip():
        print(f"   ⚠️  服务状态码: {http_code.strip()},可能需要更多时间启�?)
    else:
        print("   �?无法访问服务,请检查容器状�?)
    
    # 步骤5: 验证JVM配置已恢�?
    print("\n5️⃣  验证JVM配置...")
    check_config_cmd = f"grep -A 5 'ENTRYPOINT' {compose_file} | grep Xmx"
    config_output, _ = execute_ssh_command(check_config_cmd)
    
    if "-Xmx512m" in config_output:
        print("   �?JVM堆内存配置已恢复为正常�?-Xmx512m)")
    else:
        print("   ⚠️  配置可能未正确恢�?当前配置:")
        print(f"      {config_output.strip()}")
    
    # 步骤6: 清理Heap Dump文件
    print("\n6️⃣  清理Heap Dump文件...")
    cleanup_cmd = f"docker exec {container_name} find /app -name '*.hprof' -delete 2>/dev/null || true"
    execute_ssh_command(cleanup_cmd)
    print("   �?清理完成")
    
    print("\n" + "="*80)
    print("【Case04】环境恢复完�?")
    print("="*80)
    print("\n💡 验证建议:")
    print("   1. 访问前端页面确认功能正常")
    print("   2. 检查容器日志无异常: docker logs ruoyi-app --tail 50")
    print("   3. 监控系统资源使用情况")
    print("   4. 确认与Case03(Linux OOM)的区�?)
    print()


def resume_case05():
    """Case05: 恢复MySQL主从复制环境"""
    print("\n" + "="*80)
    print("【Case05】恢复MySQL主从复制环境")
    print("="*80)
    print("\n⚠️  此场景暂未实�?敬请期待...")
    print()


def main():
    """主函�?""
    parser = argparse.ArgumentParser(
        description='恢复故障测试环境',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python resumeCase.py --case 1          # 恢复Case01环境
  python resumeCase.py                   # 交互式选择
        """
    )
    parser.add_argument(
        '--case', 
        type=int, 
        choices=[1, 2, 3, 4, 5],
        help='选择要恢复的case编号(1-5)'
    )
    
    args = parser.parse_args()
    
    if not args.case:
        # 交互式选择
        print("\n" + "="*80)
        print("请选择要恢复的故障场景:")
        print("="*80)
        print("1. MySQL连接池耗尽导致后端服务不可�?)
        print("2. MySQL慢查询导致CPU飙升和应用超�?)
        print("3. Docker容器内存泄漏导致频繁OOM重启")
        print("4. Nginx反向代理配置错误导致502/504")
        print("5. MySQL主从复制延迟导致数据不一�?)
        print("="*80)
        
        try:
            choice = input("\n请输入case编号(1-5): ").strip()
            args.case = int(choice)
        except (ValueError, EOFError):
            print("�?无效输入")
            return
    
    # 根据选择调用对应函数
    case_functions = {
        1: resume_case01,
        2: resume_case02,
        3: resume_case03,
        4: resume_case04,
        5: resume_case05
    }
    
    if args.case in case_functions:
        print(f"\n🔄 开始恢�?Case{args.case:02d} 环境...")
        case_functions[args.case]()
    else:
        print(f"�?无效的case编号: {args.case}")


if __name__ == "__main__":
    main()
