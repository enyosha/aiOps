"""
测试 SSH 连接并检�?Docker 状�?
"""
import paramiko
import warnings
warnings.filterwarnings('ignore')

def test_ssh_connection(host, key_path, username='root', port=22):
    """测试 SSH 连接并执行命�?""
    print(f"\n{'='*70}")
    print(f"测试服务�? {host}")
    print(f"{'='*70}")
    
    try:
        # 加载 SSH 密钥
        private_key = None
        key_types = [
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
        ]
        
        for key_type in key_types:
            try:
                private_key = key_type.from_private_key_file(key_path)
                print(f"�?成功加载密钥 (类型: {key_type.__name__})")
                break
            except paramiko.SSHException as e:
                continue
        
        if not private_key:
            print(f"�?无法识别的密钥格�? {key_path}")
            return
        
        # 建立连接
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        print(f"正在连接�?{host}...")
        ssh_client.connect(
            hostname=host,
            port=port,
            username=username,
            pkey=private_key,
            timeout=30
        )
        print(f"�?SSH 连接成功\n")
        
        # 执行命令 1: 检�?Docker 服务状�?
        print("1. 检�?Docker 服务状�?")
        stdin, stdout, stderr = ssh_client.exec_command(
            "systemctl is-active docker 2>/dev/null || service docker status 2>/dev/null || echo 'Docker status check failed'"
        )
        docker_status = stdout.read().decode('utf-8').strip()
        print(f"   {docker_status}\n")
        
        # 执行命令 2: 查看所有容器（包括已停止的�?
        print("2. 查看所有容�?(docker ps -a):")
        stdin, stdout, stderr = ssh_client.exec_command(
            "docker ps -a --format '{{.Names}}\\t{{.Status}}\\t{{.Ports}}'"
        )
        output = stdout.read().decode('utf-8').strip()
        error_output = stderr.read().decode('utf-8').strip()
        
        if error_output:
            print(f"   �?错误: {error_output}")
        elif output:
            containers = output.splitlines()
            print(f"   发现 {len(containers)} 个容�?")
            for container in containers:
                parts = container.split('\t')
                name = parts[0] if len(parts) > 0 else 'N/A'
                status = parts[1] if len(parts) > 1 else 'N/A'
                ports = parts[2] if len(parts) > 2 else 'N/A'
                print(f"   - {name:30s} | 状�? {status:20s} | 端口: {ports}")
        else:
            print(f"   ⚠️ 没有任何容器（包括已停止的）\n")
        
        # 执行命令 3: 检查是否有 docker-compose 文件
        print("\n3. 查找 docker-compose 文件:")
        stdin, stdout, stderr = ssh_client.exec_command(
            "find / -maxdepth 4 -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' 2>/dev/null | head -5"
        )
        compose_files = stdout.read().decode('utf-8').strip()
        if compose_files:
            print(f"   找到以下 docker-compose 文件:")
            for f in compose_files.splitlines():
                print(f"   - {f}")
        else:
            print(f"   ⚠️ 未找�?docker-compose 文件")
        
        # 执行命令 4: 检查磁盘空�?
        print("\n4. 磁盘使用情况:")
        stdin, stdout, stderr = ssh_client.exec_command("df -h / | tail -1")
        disk_info = stdout.read().decode('utf-8').strip()
        print(f"   {disk_info}")
        
        ssh_client.close()
        print(f"\n�?测试完成\n")
        
    except Exception as e:
        print(f"�?连接失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 测试前端服务�?
    test_ssh_connection(
        host="8.146.236.55",
        key_path="c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/aiOps_Server.pem",
        username="root",
        port=22
    )
    
    # 测试后端服务�?
    test_ssh_connection(
        host="8.130.131.36",
        key_path="c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/aiOps.pem",
        username="root",
        port=22
    )
