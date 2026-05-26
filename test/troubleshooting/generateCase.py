"""
统一构建所有故障测试环�?
支持通过命令行参数或交互式选择要构建的case
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


def generate_case01():
    """
    Case01: Tomcat线程池耗尽导致请求超时
    
    故障原理:
    - RuoYi使用Spring Boot内置Tomcat作为Web服务�?
    - 正常配置: server.tomcat.threads.max=800, min-spare=100
    - 将max改为5,高并发时线程池迅速耗尽
    - 新请求进入等待队�?accept-count=1000),超过后返�?04超时
    """
    print("\n" + "="*80)
    print("【Case01】构建Tomcat线程池耗尽故障")
    print("="*80)
    
    container_name = "ruoyi-app"
    host_config_dir = "/opt/services/ruoyi/config"  # 宿主机配置目�?
    
    # 步骤1: 在宿主机创建覆盖配置文件(Spring Boot支持外部配置)
    print("\n1️⃣  创建Tomcat线程池覆盖配�?..")
    
    # 创建配置目录
    mkdir_cmd = f"sudo mkdir -p {host_config_dir}"
    execute_ssh_command(mkdir_cmd)
    
    # 写入覆盖配置(Spring Boot会优先读取外部config/application.yml)
    config_content = """server:
  tomcat:
    threads:
      max: 5
      min-spare: 2
    accept-count: 10
"""
    
    # 使用cat heredoc写入文件
    write_cmd = f"""sudo bash -c 'cat > {host_config_dir}/application.yml << EOF
{config_content}
EOF'"""
    output, error = execute_ssh_command(write_cmd)
    
    if error:
        print(f"   �?创建配置文件失败: {error}")
        return
    
    print(f"   �?配置文件已创�? {host_config_dir}/application.yml")
    print(f"   📝 内容: server.tomcat.threads.max=5, min-spare=2")
    
    # 步骤2: 停止当前容器
    print("\n2️⃣  停止ruoyi-app容器...")
    stop_cmd = f"docker stop {container_name}"
    execute_ssh_command(stop_cmd)
    print("   �?容器已停�?)
    
    # 步骤3: 重新启动容器并挂载配置文�?
    print("\n3️⃣  重新启动容器并挂载外部配�?..")
    
    # 先删除旧容器
    rm_cmd = f"docker rm {container_name}"
    execute_ssh_command(rm_cmd)
    
    # 使用docker run重新启动,挂载外部配置文件�?config目录
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
  -v {host_config_dir}/application.yml:/app/config/application.yml \
  --memory=1G \
  --cpus=2.0 \
  --network services_services-network \
  ruoyi-app:latest"""
    
    output, error = execute_ssh_command(restart_cmd)
    
    if error and "Error" in error:
        print(f"   ⚠️  启动警告: {error}")
        print("   💡 尝试使用现有镜像名称...")
        # 如果ruoyi-app:latest不存�?尝试其他可能的镜像名
        images_cmd = "docker images | grep ruoyi"
        img_output, _ = execute_ssh_command(images_cmd)
        print(f"   📋 可用镜像:\n{img_output}")
    else:
        print("   �?容器已启�?)
    
    # 步骤4: 等待容器启动
    print("\n4️⃣  等待容器启动(�?0�?...")
    for i in range(30, 0, -5):
        print(f"   �?剩余 {i} �?..", end='\r')
        time.sleep(5)
    print("   �?容器启动完成")
    
    # 步骤5: 触发高并发请求以耗尽线程�?
    print("\n5️⃣  触发高并发请求以耗尽线程�?..")
    stress_cmd = """
        for i in {1..50}; do 
            curl -s http://localhost:80/system/user/list > /dev/null & 
        done
        wait
    """
    execute_ssh_command(stress_cmd)
    print("   �?并发请求已发�?50�?")
    
    # 步骤6: 验证故障现象
    print("\n6️⃣  验证故障现象...")
    logs_cmd = f"docker logs {container_name} --tail 100"
    logs, _ = execute_ssh_command(logs_cmd)
    
    # 检查是否出现线程池相关警告
    warning_keywords = [
        "thread",
        "executor",
        "timeout",
        "rejected",
        "queue"
    ]
    
    found_warnings = []
    for keyword in warning_keywords:
        if keyword.lower() in logs.lower():
            found_warnings.append(keyword)
    
    if found_warnings:
        print(f"   �?故障构建成功! 检测到以下关键�?")
        for warn in found_warnings:
            print(f"      - {warn}")
        
        print("\n   📋 关键日志片段:")
        print("   " + "-"*76)
        for line in logs.split('\n')[-20:]:
            if any(kw.lower() in line.lower() for kw in warning_keywords):
                print(f"   {line[:150]}")
        print("   " + "-"*76)
    else:
        print("   ⚠️  未检测到明显的线程池警告")
        print("   💡 可能需要更多并发请求或等待更长时间")
        print("\n   📋 最近日�?")
        print("   " + "-"*76)
        for line in logs.split('\n')[-10:]:
            print(f"   {line[:150]}")
        print("   " + "-"*76)
    
    # 测试响应时间
    print("\n7️⃣  测试当前响应时间...")
    response_test_cmd = "curl -o /dev/null -s -w 'HTTP Code: %{http_code}, Time: %{time_total}s' http://localhost:80/login"
    response_output, _ = execute_ssh_command(response_test_cmd)
    print(f"   📊 响应测试结果: {response_output.strip()}")
    
    print("\n" + "="*80)
    print("【Case01】故障环境构建完�?")
    print("="*80)
    print("\n💡 下一步操�?")
    print("   1. 运行诊断Agent测试诊断能力")
    print("   2. 观察高并发下的响应时间变�?)
    print("   3. 测试完成后执�? python resumeCase.py --case 1 恢复环境")
    print()


def generate_case03():
    """
    Case03: MySQL连接池耗尽导致后端服务不可�?
    
    故障原理:
    - RuoYi使用Druid连接�?默认maxActive=20
    - 将maxActive改为2,模拟配置错误
    - 并发请求时连接池迅速耗尽,新请求无法获取连�?
    """
    print("\n" + "="*80)
    print("【Case03】构建MySQL连接池耗尽故障")
    print("="*80)
    
    container_name = "ruoyi-app"
    config_file = "/app/ruoyi-admin/src/main/resources/application-druid.yml"
    
    # 步骤1: 备份原始配置
    print("\n1️⃣  备份原始配置文件...")
    backup_cmd = f"docker exec {container_name} cp {config_file} {config_file}.bak"
    output, error = execute_ssh_command(backup_cmd)
    
    if error and "No such file" in error:
        # 如果容器内路径不�?尝试其他常见路径
        print("   ⚠️  配置文件路径可能不同,尝试查找...")
        find_cmd = f"docker exec {container_name} find / -name 'application-druid.yml' 2>/dev/null"
        output, _ = execute_ssh_command(find_cmd)
        if output.strip():
            config_file = output.strip().split('\n')[0]
            print(f"   �?找到配置文件: {config_file}")
            backup_cmd = f"docker exec {container_name} cp {config_file} {config_file}.bak"
            execute_ssh_command(backup_cmd)
        else:
            print("   �?未找到配置文�?请手动确认路�?)
            return
    
    print("   �?配置备份完成")
    
    # 步骤2: 修改连接池配置为极小�?
    print("\n2️⃣  修改Druid连接池最大连接数�?...")
    modify_cmd = f"""docker exec {container_name} sh -c "
        sed -i 's/maxActive:.*/maxActive: 2/' {config_file} &&
        sed -i 's/minIdle:.*/minIdle: 1/' {config_file} &&
        sed -i 's/initialSize:.*/initialSize: 1/' {config_file}
    """
    output, error = execute_ssh_command(modify_cmd)
    
    if error:
        print(f"   �?修改配置失败: {error}")
        return
    
    print("   �?配置修改完成")
    print("      - maxActive: 20 �?2")
    print("      - minIdle: 10 �?1")
    print("      - initialSize: 5 �?1")
    
    # 步骤3: 重启容器使配置生�?
    print("\n3️⃣  重启ruoyi-app容器...")
    restart_cmd = f"docker restart {container_name}"
    execute_ssh_command(restart_cmd)
    
    # 步骤4: 等待容器启动
    print("\n4️⃣  等待容器启动(�?0�?...")
    for i in range(30, 0, -5):
        print(f"   �?剩余 {i} �?..", end='\r')
        time.sleep(5)
    print("   �?容器启动完成")
    
    # 步骤5: 触发并发请求以耗尽连接�?
    print("\n5️⃣  触发并发请求以耗尽连接�?..")
    stress_cmd = """
        for i in {1..10}; do 
            curl -s http://localhost:80/api/system/user/list > /dev/null & 
        done
        wait
    """
    execute_ssh_command(stress_cmd)
    print("   �?并发请求已发�?)
    
    # 步骤6: 验证故障现象
    print("\n6️⃣  验证故障现象...")
    logs_cmd = f"docker logs {container_name} --tail 100"
    logs, _ = execute_ssh_command(logs_cmd)
    
    # 检查是否出现连接池相关错误
    error_keywords = [
        "connection pool",
        "DruidDataSource",
        "maxActive",
        "GetConnectionTimeoutException",
        "pool exhausted"
    ]
    
    found_errors = []
    for keyword in error_keywords:
        if keyword.lower() in logs.lower():
            found_errors.append(keyword)
    
    if found_errors:
        print(f"   �?故障构建成功! 检测到以下错误关键�?")
        for err in found_errors:
            print(f"      - {err}")
        
        print("\n   📋 关键日志片段:")
        print("   " + "-"*76)
        for line in logs.split('\n')[-20:]:
            if any(kw.lower() in line.lower() for kw in error_keywords):
                print(f"   {line[:150]}")
        print("   " + "-"*76)
    else:
        print("   ⚠️  未检测到明显的连接池错误")
        print("   💡 可能需要更多并发请求或等待更长时间")
        print("\n   📋 最近日�?")
        print("   " + "-"*76)
        for line in logs.split('\n')[-10:]:
            print(f"   {line[:150]}")
        print("   " + "-"*76)
    
    print("\n" + "="*80)
    print("【Case03】故障环境构建完�?")
    print("="*80)
    print("\n💡 下一步操�?")
    print("   1. 运行诊断Agent测试诊断能力")
    print("   2. 测试完成后执�? python resumeCase.py --case 3 恢复环境")
    print()


def generate_case02():
    """
    Case02: 静态资源加载失�?404/403错误)
    
    故障原理:
    - RuoYi前端页面依赖CSS/JS等静态资�?
    - 删除关键静态文件或修改ResourcesConfig配置
    - 导致浏览器无法加载样式和脚本,页面显示异常
    """
    print("\n" + "="*80)
    print("【Case02】构建静态资源加载失败故�?)
    print("="*80)
    
    container_name = "ruoyi-app"
    static_dir = "/app/ruoyi-admin/src/main/resources/static"
    
    # 步骤1: 备份静态资源目�?
    print("\n1️⃣  备份静态资源目�?..")
    backup_cmd = f"docker exec {container_name} cp -r {static_dir} {static_dir}.bak"
    output, error = execute_ssh_command(backup_cmd)
    
    if error:
        print(f"   ⚠️  备份可能失败: {error}")
        print("   💡 尝试查找静态资源目�?..")
        find_cmd = f"docker exec {container_name} find /app -type d -name 'static' 2>/dev/null"
        output, _ = execute_ssh_command(find_cmd)
        if output.strip():
            static_dir = output.strip().split('\n')[0]
            print(f"   �?找到静态资源目�? {static_dir}")
            backup_cmd = f"docker exec {container_name} cp -r {static_dir} {static_dir}.bak"
            execute_ssh_command(backup_cmd)
        else:
            print("   �?未找到静态资源目�?)
            return
    
    print("   �?静态资源备份完�?)
    
    # 步骤2: 删除关键CSS文件以模拟资源缺�?
    print("\n2️⃣  删除关键CSS文件...")
    delete_cmd = f"""docker exec {container_name} sh -c "
        rm -rf {static_dir}/css/*.css &&
        rm -rf {static_dir}/ajax/libs/bootstrap-table/*.css
    """
    output, error = execute_ssh_command(delete_cmd)
    
    if error:
        print(f"   ⚠️  删除操作警告: {error}")
    else:
        print("   �?CSS文件已删�?)
    
    # 步骤3: 删除部分JS文件
    print("\n3️⃣  删除部分JavaScript文件...")
    delete_js_cmd = f"""docker exec {container_name} sh -c "
        rm -f {static_dir}/ruoyi/js/ry-ui.js &&
        rm -f {static_dir}/ajax/libs/layer/*.js
    """
    output, error = execute_ssh_command(delete_js_cmd)
    
    if error:
        print(f"   ⚠️  删除操作警告: {error}")
    else:
        print("   �?JavaScript文件已删�?)
    
    # 步骤4: 验证文件已删�?
    print("\n4️⃣  验证文件删除情况...")
    check_cmd = f"docker exec {container_name} ls {static_dir}/css/ 2>&1 | head -5"
    check_output, _ = execute_ssh_command(check_cmd)
    
    if not check_output.strip() or "No such file" in check_output:
        print("   �?确认CSS目录已清空或不存�?)
    else:
        print(f"   ℹ️  CSS目录内容: {check_output.strip()[:100]}")
    
    # 步骤5: 无需重启容器,静态资源变更立即生�?
    print("\n5️⃣  静态资源变更已生效(无需重启)")
    
    # 步骤6: 验证故障现象
    print("\n6️⃣  验证故障现象...")
    test_cmd = "curl -s -o /dev/null -w '%{http_code}' http://localhost:80/css/style.css"
    css_status, _ = execute_ssh_command(test_cmd)
    
    test_js_cmd = "curl -s -o /dev/null -w '%{http_code}' http://localhost:80/ruoyi/js/ry-ui.js"
    js_status, _ = execute_ssh_command(test_js_cmd)
    
    print(f"   📊 CSS文件状态码: {css_status.strip()}")
    print(f"   📊 JS文件状态码: {js_status.strip()}")
    
    if css_status.strip() == "404" or js_status.strip() == "404":
        print("   �?故障构建成功! 静态资源返�?04错误")
    else:
        print("   ⚠️  资源仍可访问,可能需要清除浏览器缓存")
    
    print("\n" + "="*80)
    print("【Case02】故障环境构建完�?")
    print("="*80)
    print("\n💡 下一步操�?")
    print("   1. 在浏览器中访问前端页�?观察样式丢失情况")
    print("   2. 打开浏览器控制台(F12),查看Network标签中的404错误")
    print("   3. 运行诊断Agent测试诊断能力")
    print("   4. 测试完成后执�? python resumeCase.py --case 2 恢复环境")
    print()


def generate_case05():
    """
    Case05: MySQL慢查询导致CPU飙升和应用超�?
    
    故障原理:
    - 在MySQL中创建一个大�?10�?�?且无索引
    - 执行全表扫描的复杂查�?
    - MySQL CPU使用率飙升到90%+
    - 应用接口响应时间超过10秒甚至超�?
    """
    print("\n" + "="*80)
    print("【Case05】构建MySQL慢查询导致CPU飙升故障")
    print("="*80)
    
    mysql_container = "mysql"  # 假设MySQL容器名为mysql
    db_user = "root"
    db_password = ".My19w2fLC6Ob"
    db_name = "ry"
    
    # 步骤1: 检查MySQL容器是否运行
    print("\n1️⃣  检查MySQL容器状�?..")
    check_cmd = f"docker ps | grep {mysql_container}"
    output, _ = execute_ssh_command(check_cmd)
    
    if mysql_container not in output:
        print(f"   �?MySQL容器 '{mysql_container}' 未运�?)
        print("   💡 请确认MySQL容器名称是否正确")
        return
    
    print("   �?MySQL容器运行�?)
    
    # 步骤2: 创建测试大表(无索�?
    print("\n2️⃣  创建测试大表(10万行,无索�?...")
    create_table_sql = f"""
    DROP TABLE IF EXISTS test_slow_query;
    CREATE TABLE test_slow_query (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100),
        email VARCHAR(100),
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB;
    """
    
    create_cmd = f"docker exec {mysql_container} mysql -u{db_user} -p'{db_password}' {db_name} -e \"{create_table_sql.replace(chr(10), ' ')}\""
    output, error = execute_ssh_command(create_cmd)
    
    if error and "ERROR" in error:
        print(f"   ⚠️  创建表警�? {error[:200]}")
    else:
        print("   �?测试表创建成�?)
    
    # 步骤3: 插入大量测试数据
    print("\n3️⃣  插入10万行测试数据(可能需要几分钟)...")
    insert_sql = """
    INSERT INTO test_slow_query (name, email, description)
    SELECT 
        CONCAT('user_', seq),
        CONCAT('user_', seq, '@test.com'),
        CONCAT('Description for user ', seq, ' - This is a long text to increase row size')
    FROM (
        SELECT @row := @row + 1 AS seq
        FROM information_schema.columns c1, information_schema.columns c2,
        (SELECT @row := 0) r
        LIMIT 100000
    ) nums;
    """
    
    insert_cmd = f"docker exec {mysql_container} mysql -u{db_user} -p'{db_password}' {db_name} -e \"{insert_sql.replace(chr(10), ' ')}\""
    print("   �?正在插入数据,请稍�?..")
    output, error = execute_ssh_command(insert_cmd, timeout=120)
    
    if error and "ERROR" in error:
        print(f"   ⚠️  插入数据警告: {error[:200]}")
        print("   💡 尝试使用简化版插入...")
        # 简化版:只插�?万行
        simple_insert = """
        INSERT INTO test_slow_query (name, email, description)
        SELECT CONCAT('user_', n), CONCAT('user_', n, '@test.com'), 'Test data'
        FROM (SELECT @row := @row + 1 AS n FROM information_schema.columns, (SELECT @row := 0) r LIMIT 10000) nums;
        """
        simple_cmd = f"docker exec {mysql_container} mysql -u{db_user} -p'{db_password}' {db_name} -e \"{simple_insert.replace(chr(10), ' ')}\""
        execute_ssh_command(simple_cmd, timeout=60)
        print("   �?已插�?万行测试数据")
    else:
        print("   �?已插�?0万行测试数据")
    
    # 步骤4: 验证数据�?
    print("\n4️⃣  验证数据�?..")
    count_sql = "SELECT COUNT(*) FROM test_slow_query;"
    count_cmd = f"docker exec {mysql_container} mysql -u{db_user} -p'{db_password}' {db_name} -e \"{count_sql}\""
    count_output, _ = execute_ssh_command(count_cmd)
    print(f"   📊 表中数据行数: {count_output.strip().split()[-1] if count_output.strip() else '未知'}")
    
    # 步骤5: 执行慢查询以触发CPU飙升
    print("\n5️⃣  执行慢查询以触发CPU飙升...")
    slow_query_sql = """
    SELECT t1.*, t2.* 
    FROM test_slow_query t1 
    JOIN test_slow_query t2 ON t1.description LIKE CONCAT('%', t2.name, '%')
    WHERE t1.id > 1000 AND t2.id < 50000
    ORDER BY t1.created_at DESC;
    """
    
    # 在后台持续运行慢查询
    run_query_cmd = f"""docker exec {mysql_container} nohup mysql -u{db_user} -p'{db_password}' {db_name} -e \"{slow_query_sql.replace(chr(10), ' ')}\" > /dev/null 2>&1 &"""
    execute_ssh_command(run_query_cmd)
    print("   �?慢查询已在后台运�?)
    
    # 步骤6: 等待并验证CPU使用�?
    print("\n6️⃣  等待10秒后检查CPU使用�?..")
    time.sleep(10)
    
    cpu_check_cmd = "top -bn1 | grep -i mysql | head -3"
    cpu_output, _ = execute_ssh_command(cpu_check_cmd)
    
    if cpu_output.strip():
        print("   📊 MySQL进程CPU使用情况:")
        for line in cpu_output.strip().split('\n')[:3]:
            print(f"      {line[:100]}")
    else:
        print("   ⚠️  未检测到MySQL进程")
    
    print("\n" + "="*80)
    print("【Case05】故障环境构建完�?")
    print("="*80)
    print("\n💡 下一步操�?")
    print("   1. 运行诊断Agent测试诊断能力")
    print("   2. 观察CPU使用率和查询响应时间")
    print("   3. 测试完成后执�? python resumeCase.py --case 5 恢复环境")
    print()


def generate_case03():
    """Case03: Docker容器OOM重启"""
    print("\n" + "="*80)
    print("【Case03】构建Docker容器OOM重启故障")
    print("="*80)
    print("\n⚠️  此场景暂未实�?敬请期待...")
    print()


def generate_case04():
    """
    Case04: JVM堆内存溢出导致应用崩�?
    
    故障原理:
    - RuoYi是Spring Boot应用,运行在JVM�?
    - 正常JVM配置: -Xms256m -Xmx512m
    - 将堆内存限制为极小�?�?4m),快速触发OutOfMemoryError
    - 与Case03的区�? Case03是Linux内核OOM Killer杀死容�?Case04是JVM内部堆内存溢�?
    """
    print("\n" + "="*80)
    print("【Case04】构建JVM堆内存溢出故�?)
    print("="*80)
    
    container_name = "ruoyi-app"
    
    # 步骤1: 备份原始Docker Compose配置
    print("\n1️⃣  备份原始docker-compose配置...")
    compose_file = "/opt/source/RuoYi/docker-compose.ruoyi.yml"
    backup_cmd = f"cp {compose_file} {compose_file}.bak"
    output, error = execute_ssh_command(backup_cmd)
    
    if error:
        print(f"   ⚠️  备份失败: {error}")
        print("   💡 请确认文件路径是否正�?)
        return
    
    print("   �?配置备份完成")
    
    # 步骤2: 修改JVM参数,将堆内存限制为极小�?
    print("\n2️⃣  修改JVM堆内存参数为64m...")
    modify_cmd = f"""sed -i 's/-Xms256m/-Xms64m/g; s/-Xmx512m/-Xmx64m/g' {compose_file}"""
    output, error = execute_ssh_command(modify_cmd)
    
    if error:
        print(f"   �?修改配置失败: {error}")
        return
    
    print("   �?JVM参数修改完成")
    print("      - Xms: 256m �?64m")
    print("      - Xmx: 512m �?64m")
    
    # 步骤3: 重启容器使新JVM参数生效
    print("\n3️⃣  重启ruoyi-app容器...")
    restart_cmd = f"cd /opt/source/RuoYi && docker-compose -f docker-compose.ruoyi.yml up -d"
    execute_ssh_command(restart_cmd)
    
    # 步骤4: 等待容器启动
    print("\n4️⃣  等待容器启动(�?0�?...")
    for i in range(30, 0, -5):
        print(f"   �?剩余 {i} �?..", end='\r')
        time.sleep(5)
    print("   �?容器启动完成")
    
    # 步骤5: 触发大对象创建以快速耗尽堆内�?
    print("\n5️⃣  触发大对象创建以耗尽堆内�?..")
    # 通过访问需要大量内存的接口来触发OOM
    stress_cmd = """
        for i in {1..20}; do 
            curl -s http://localhost:8080/system/user/list?pageNum=1&pageSize=1000 > /dev/null & 
        done
        wait
    """
    execute_ssh_command(stress_cmd)
    print("   �?并发请求已发�?)
    
    # 步骤6: 验证故障现象
    print("\n6️⃣  验证故障现象...")
    logs_cmd = f"docker logs {container_name} --tail 100"
    logs, _ = execute_ssh_command(logs_cmd)
    
    # 检查是否出现OutOfMemoryError
    error_keywords = [
        "OutOfMemoryError",
        "Java heap space",
        "GC overhead limit exceeded",
        "heap dump"
    ]
    
    found_errors = []
    for keyword in error_keywords:
        if keyword.lower() in logs.lower():
            found_errors.append(keyword)
    
    if found_errors:
        print(f"   �?故障构建成功! 检测到以下错误关键�?")
        for err in found_errors:
            print(f"      - {err}")
        
        print("\n   📋 关键日志片段:")
        print("   " + "-"*76)
        for line in logs.split('\n')[-20:]:
            if any(kw.lower() in line.lower() for kw in error_keywords):
                print(f"   {line[:150]}")
        print("   " + "-"*76)
    else:
        print("   ⚠️  未检测到明显的OutOfMemoryError")
        print("   💡 可能需要更多并发请求或等待更长时间")
        print("\n   📋 最近日�?")
        print("   " + "-"*76)
        for line in logs.split('\n')[-10:]:
            print(f"   {line[:150]}")
        print("   " + "-"*76)
    
    # 检查容器状�?
    print("\n7️⃣  检查容器状�?..")
    status_cmd = f"docker ps | grep {container_name}"
    status_output, _ = execute_ssh_command(status_cmd)
    
    if container_name in status_output:
        print("   ℹ️  容器仍在运行(JVM崩溃但Docker容器未退�?")
    else:
        print("   ⚠️  容器已退�?)
    
    print("\n" + "="*80)
    print("【Case04】故障环境构建完�?")
    print("="*80)
    print("\n💡 下一步操�?")
    print("   1. 运行诊断Agent测试诊断能力")
    print("   2. 注意区分JVM OOM和Linux OOM Killer(Case03)")
    print("   3. 测试完成后执�? python resumeCase.py --case 4 恢复环境")
    print()


def generate_case05():
    """Case05: MySQL主从复制延迟"""
    print("\n" + "="*80)
    print("【Case05】构建MySQL主从复制延迟故障")
    print("="*80)
    print("\n⚠️  此场景暂未实�?敬请期待...")
    print()


def main():
    """主函�?""
    parser = argparse.ArgumentParser(
        description='构建故障测试环境',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python generateCase.py --case 1          # 构建Case01故障环境
  python generateCase.py                   # 交互式选择
        """
    )
    parser.add_argument(
        '--case', 
        type=int, 
        choices=[1, 2, 3, 4, 5],
        help='选择要构建的case编号(1-5)'
    )
    
    args = parser.parse_args()
    
    if not args.case:
        # 交互式选择
        print("\n" + "="*80)
        print("请选择要构建的故障场景:")
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
        1: generate_case01,
        2: generate_case02,
        3: generate_case03,
        4: generate_case04,
        5: generate_case05
    }
    
    if args.case in case_functions:
        print(f"\n🚀 开始构�?Case{args.case:02d} 故障环境...")
        case_functions[args.case]()
    else:
        print(f"�?无效的case编号: {args.case}")


if __name__ == "__main__":
    main()
