"""
测试诊断Agent的日志分析深度优化
验证日志统计分析和交叉验证功能是否正常工作
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()


async def test_diagnosis_with_log_analysis():
    """测试带日志统计分析的诊断流程"""
    print("\n" + "="*80)
    print("测试诊断Agent日志分析深度优化")
    print("="*80)
    
    from Routing.diagnosis_agent import diagnosis_workflow
    
    # 创建测试状态，模拟真实场景
    test_state = {
        "user_query": "系统访问缓慢，部分请求超时",
        "container_name": "ruoyi-app",
        "current_step": "start",
        "iteration_count": 0,
        "max_iterations": 10,
        "servers_config": {
            "backend": {
                "ssh_host": "8.130.131.36",
                "ssh_port": 22,
                "ssh_user": "root",
                "ssh_key_path": "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/aiOps_Server.pem"
            },
            "frontend": {
                "ssh_host": "8.146.236.55",
                "ssh_port": 22,
                "ssh_user": "root",
                "ssh_key_path": "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/aiOps_Server.pem"
            }
        },
        # 模拟已收集的容器信息
        "discovered_containers": [
            {
                "name": "ruoyi-frontend",
                "type": "frontend",
                "ports": "80->80/tcp",
                "status": "running",
                "server": "8.146.236.55",
                "issue": None
            },
            {
                "name": "ruoyi-app",
                "type": "backend",
                "ports": "8080->8080/tcp",
                "status": "running",
                "server": "8.130.131.36",
                "issue": None
            },
            {
                "name": "mysql",
                "type": "database",
                "ports": "3306->3306/tcp",
                "status": "running",
                "server": "8.130.131.36",
                "issue": None
            },
            {
                "name": "redis",
                "type": "redis",  # 修改为 'redis' 而不是 'cache'
                "ports": "6379->6379/tcp",
                "status": "running",
                "server": "8.130.131.36",
                "issue": None
            }
        ],
        # 模拟收集到的日志数据（包含前端和后端日志）
        "logs_data": """--- FRONTEND 服务日志 (ruoyi-frontend, 最近30分钟, 16行) ---
93.123.72.166 - - [19/May/2026:12:15:08 +0800] "GET /SDK/webLanguage HTTP/1.1" 200 4612 "-" "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36 Edg/90.0.818.46" "-"
203.242.185.211 - - [19/May/2026:12:19:08 +0800] "GET / HTTP/1.0" 200 12909 "-" "ivre-masscan/1.3 https://github.com/robertdavidgraham/" "-"
66.132.172.38 - - [19/May/2026:12:31:32 +0800] "GET / HTTP/1.1" 200 4612 "-" "Mozilla/5.0 (compatible; CensysInspect/1.1; +https://about.censys.io/)" "-"
66.132.172.38 - - [19/May/2026:12:31:33 +0800] "PRI * HTTP/2.0" 400 157 "-" "-" "-"
66.132.172.38 - - [19/May/2026:12:31:33 +0800] "GET /favicon.ico HTTP/1.1" 200 5663 "-" "Mozilla/5.0 (compatible; CensysInspect/1.1; +https://about.censys.io/)" "-"
66.132.172.38 - - [19/May/2026:12:31:37 +0800] "\\x16\\x03\\x01\\x00\\xEE\\x01\\x00\\x00\\xEA\\x03\\x03\\xEE\\xF6\\x87q\\xD6z}\\xB0R\\xCA\\xDF[\\xDC\\x92H\\xF9O*\\xEB\\xC4\\xA2\\xC7Y\\x01\\xDE\\xD3\\xF8\\xC1Z\\xD1|< &AZ\\xE6\\xAB*\\xC5h\\xA5\\x99\\xFA\\xC3\\x7F^\\x19}\\xC5\\x1C\\xD6\\x5C\\x05S\\xEE>\\x12\\xA6#3\\xFC\\xF6\\xBF\\x1F\\x00&\\xCC\\xA8\\xCC\\xA9\\xC0/\\xC00\\xC0+\\xC0,\\xC0\\x13\\xC0\\x09\\xC0\\x14\\xC0" 400 157 "-" "-" "-"
66.132.172.38 - - [19/May/2026:12:31:38 +0800] "GET /wiki HTTP/1.1" 200 4612 "-" "Mozilla/5.0 (compatible; CensysInspect/1.1; +https://about.censys.io/)" "-"
66.132.172.38 - - [19/May/2026:12:31:42 +0800] "\\x16\\x03\\x01\\x00\\xEE\\x01\\x00\\x00\\xEA\\x03\\x03`$\\xE7 \\x00\\xFC\\xA0\\xA4\\x83SI\\xF8>W\\xB6\\xF2\\xF2Z~8\\xF1\\x04\\x9F\\x80\\x87qc\\xA3x\\xDB\\x94m p\\xE3\\xD5G\\xD4\\xD2\\xA5\\x96<85DYy\\xE1\\x81\\x03\\x010\\x11\\xF7M\\x80\\x16V\\xF7y\\xA0\\xF8\\xD5bs\\x00&\\xCC\\xA8\\xCC\\xA9\\xC0/\\xC00\\xC0+\\xC0,\\xC0\\x13\\xC0\\x09\\xC0\\x14\\xC0" 400 157 "-" "-" "-"
66.132.172.38 - - [19/May/2026:12:31:43 +0800] "\\x16\\x03\\x01\\x00\\xEE\\x01\\x00\\x00\\xEA\\x03\\x03\\xF5q\\xBAYq\\x86\\x88\\x9A\\x16\\x0E\\x98\\x10\\x5C@K\\x8E\\xE8\\xE5\\xA0\\x90\\xD8\\xB8h}L\\x92>i\\x14NW\\x7F \\xFE\\x16]\\xD9g)\\xFF.\\xFC" 400 157 "-" "-" "-"
123.160.175.211 - - [19/May/2026:12:32:48 +0800] "GET / HTTP/1.1" 200 4612 "-" "Mozilla/5.0 (iPad; CPU OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1" "-"
220.154.1.3 - - [19/May/2026:12:39:45 +0800] "GET /index HTTP/1.1" 304 0 "http://8.146.236.55/system/user" "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0" "-"
2026/05/19 12:40:01 [error] 29#29: *32 upstream timed out (110: Operation timed out) while connecting to upstream, client: 220.154.1.3, server: localhost, request: "GET /prod-api/getInfo HTTP/1.1", upstream: "http://8.130.131.36:8080/getInfo", host: "8.146.236.55", referrer: "http://8.146.236.55/index"
220.154.1.3 - - [19/May/2026:12:40:01 +0800] "GET /prod-api/getInfo HTTP/1.1" 504 167 "http://8.146.236.55/index" "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0" "-"
2026/05/19 12:40:11 [error] 29#29: *34 upstream timed out (110: Operation timed out) while connecting to upstream, client: 220.154.1.3, server: localhost, request: "POST /prod-api/logout HTTP/1.1", upstream: "http://8.130.131.36:8080/logout", host: "8.146.236.55", referrer: "http://8.146.236.55/index"
220.154.1.3 - - [19/May/2026:12:40:11 +0800] "POST /prod-api/logout HTTP/1.1" 504 167 "http://8.146.236.55/index" "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0" "-"

--- BACKEND 服务日志 (ruoyi-app, 最近30分钟, 50行) ---
2026-05-19 12:35:00.123 INFO  [main] com.ruoyi.RuoYiApplication - Starting RuoYiApplication v3.9.0
2026-05-19 12:35:05.456 INFO  [main] o.s.b.w.embedded.tomcat.TomcatWebServer - Tomcat started on port(s): 8080 (http) with context path ''
2026-05-19 12:35:05.789 INFO  [main] com.ruoyi.RuoYiApplication - Started RuoYiApplication in 5.666 seconds
2026-05-19 12:39:50.123 INFO  [http-nio-8080-exec-1] c.r.f.w.i.JwtAuthenticationTokenFilter - 用户登录成功: admin
2026-05-19 12:40:00.456 ERROR [http-nio-8080-exec-2] c.r.f.w.e.GlobalExceptionHandler - 请求处理异常: 
java.net.SocketTimeoutException: Read timed out
	at java.net.SocketInputStream.socketRead0(Native Method)
	at java.net.SocketInputStream.socketRead(SocketInputStream.java:116)
	at com.ruoyi.system.service.impl.SysUserService.selectUserById(SysUserService.java:45)
2026-05-19 12:40:01.789 WARN  [http-nio-8080-exec-2] o.s.w.s.m.m.a.ExceptionHandlerExceptionResolver - Resolved [org.springframework.web.client.ResourceAccessException: I/O error on GET request for "http://localhost:3306/ry": Read timed out]
2026-05-19 12:40:10.123 ERROR [http-nio-8080-exec-3] c.r.f.w.e.GlobalExceptionHandler - 请求处理异常: 
java.net.SocketTimeoutException: Read timed out
	at java.net.SocketInputStream.socketRead0(Native Method)
	at com.ruoyi.common.core.domain.AjaxResult.error(AjaxResult.java:38)
2026-05-19 12:40:11.456 WARN  [http-nio-8080-exec-3] o.s.w.s.m.m.a.ExceptionHandlerExceptionResolver - Resolved exception
""",
        "logs_collected_ranges": [
            {"range_minutes": 30, "line_count": 16, "service": "frontend"},
            {"range_minutes": 30, "line_count": 50, "service": "backend"}
        ],
        "memory_info": """              total        used        free      shared  buff/cache   available
Mem:           7.8Gi       5.2Gi       1.1Gi       256Mi       1.5Gi       2.3Gi
Swap:          2.0Gi       0.0Ki       2.0Gi""",
        "cpu_info": """top - 12:45:00 up 10 days,  3:22,  1 user,  load average: 0.52, 0.58, 0.59
Tasks: 156 total,   1 running, 155 sleeping,   0 stopped,   0 zombie
%Cpu(s): 12.3 us,  3.2 sy,  0.0 ni, 84.1 id,  0.2 wa,  0.0 hi,  0.2 si,  0.0 st""",
        "mysql_status": "[OK] MySQL 运行正常",
        "service_status": "所有服务正常运行",
        "docker_stats_info": """
【容器资源使用情况】
CONTAINER ID   NAME             CPU %     MEM USAGE / LIMIT     MEM %     NET I/O           BLOCK I/O         PIDS
abc123def456   ruoyi-frontend   0.05%     15.2MiB / 7.8GiB      0.19%     1.2MB / 850kB     0B / 0B           3
def789ghi012   ruoyi-app        15.2%     512.8MiB / 7.8GiB     6.42%     2.5MB / 1.8MB     125MB / 45MB      45
ghi345jkl678   mysql            2.1%      256.4MiB / 7.8GiB     3.21%     850kB / 1.2MB     89MB / 125MB      28
jkl901mno234   redis            0.8%      12.5MiB / 7.8GiB      0.16%     450kB / 320kB     0B / 0B           5
"""
    }
    
    print("\n✅ 测试状态已准备就绪")
    print(f"   - 容器数量: {len(test_state['discovered_containers'])}")
    print(f"   - 前端日志: 16行")
    print(f"   - 后端日志: 50行")
    print(f"   - 内存可用: 2.3Gi")
    print(f"   - CPU使用率: 12.3%")
    
    print("\n🔄 开始执行诊断流程...")
    print("="*80)
    
    try:
        # 执行诊断
        result = await diagnosis_workflow.ainvoke(test_state)
        
        print("\n" + "="*80)
        print("✅ 诊断完成!")
        print("="*80)
        
        # 检查诊断结果
        diagnosis_result = result.get('diagnosis_result', {})
        content = diagnosis_result.get('content', '')
        
        if content:
            print("\n📊 诊断报告:")
            print("-"*80)
            print(content)
            print("-"*80)
            
            # 验证报告质量
            print("\n🔍 报告质量检查:")
            checks = {
                "包含问题根因": "## 问题根因" in content,
                "包含立即执行建议": "## 立即执行" in content,
                "包含长期优化建议": "## 长期优化" in content,
                "包含服务状态": "## 服务状态" in content,
                "引用具体日志证据": any(keyword in content for keyword in ["upstream timed out", "504", "SocketTimeoutException"]),
                "提到客户端IP": "220.154.1.3" in content,
                "提到请求路径": "/prod-api" in content,
                "进行时间线分析": "12:40" in content or "12:39" in content,
                "包含当前状态验证": "【当前状态验证" in content or "当前状态" in content or "最近5分钟" in content,
                "明确区分历史/当前问题": "已恢复的历史问题" in content or "当前活跃" in content or "系统未发现当前错误" in content,
            }
            
            all_passed = True
            for check_name, passed in checks.items():
                status = "✅" if passed else "❌"
                print(f"  {status} {check_name}: {'通过' if passed else '未通过'}")
                if not passed:
                    all_passed = False
            
            if all_passed:
                print("\n🎉 所有质量检查通过!")
            else:
                print("\n⚠️  部分检查未通过，可能需要进一步优化Prompt")
        else:
            print("\n❌ 诊断结果为空!")
            print(f"完整结果: {result}")
    
    except Exception as e:
        print(f"\n❌ 诊断过程出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_diagnosis_with_log_analysis())
