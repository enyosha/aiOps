-- ============================================================
-- MySQL 连接数打满测试脚本
-- 用途：模拟大量并发连接以测试连接池管理和连接限制
-- 作者：AiOps 测试团队
-- 日期：2026-05-14
-- ============================================================

-- ============================================================
-- 第一部分：检查当前连接配置
-- ============================================================

-- 查看当前最大连接数设置
SHOW VARIABLES LIKE 'max_connections';

-- 查看当前连接使用情况
SHOW STATUS LIKE 'Threads_connected';
SHOW STATUS LIKE 'Threads_running';
SHOW STATUS LIKE 'Max_used_connections';

-- 查看当前所有连接详情
SELECT 
    ID,
    USER,
    HOST,
    DB,
    COMMAND,
    TIME,
    STATE,
    INFO
FROM information_schema.PROCESSLIST
ORDER BY TIME DESC;


-- ============================================================
-- 第二部分：创建存储过程模拟连接占用
-- ============================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS simulate_connection_hog$$

CREATE PROCEDURE simulate_connection_hog()
BEGIN
    DECLARE i INT DEFAULT 1;
    DECLARE v_delay INT;
    
    -- 模拟长时间运行的查询，占用连接
    WHILE i <= 50 DO  -- 可以根据需要调整数量
        SET v_delay = FLOOR(RAND() * 30) + 10;  -- 随机延迟10-40秒
        
        -- 执行一个耗时的操作来保持连接活跃
        SELECT SLEEP(v_delay) AS sleep_time, 
               CONCAT('Connection hog #', i) AS connection_info,
               NOW() AS start_time;
        
        SET i = i + 1;
    END WHILE;
END$$

DELIMITER ;


-- ============================================================
-- 第三部分：创建事件调度器自动产生连接负载
-- ============================================================

-- 启用事件调度器
SET GLOBAL event_scheduler = ON;

-- 创建定期事件来模拟连接压力
DELIMITER $$

DROP EVENT IF EXISTS evt_connection_stress_test$$

CREATE EVENT evt_connection_stress_test
ON SCHEDULE EVERY 1 MINUTE
STARTS CURRENT_TIMESTAMP
DO
BEGIN
    -- 创建多个临时连接来增加负载
    CALL simulate_connection_hog();
END$$

DELIMITER ;


-- ============================================================
-- 第四部分：手动触发连接压力测试
-- ============================================================

-- 方法1：直接调用存储过程（会在当前会话中执行）
-- CALL simulate_connection_hog();

-- 方法2：启动事件调度器（后台持续运行）
-- ALTER EVENT evt_connection_stress_test ENABLE;

-- 方法3：使用循环创建多个并发会话（需要在客户端执行）
/*
在MySQL客户端中，可以打开多个终端窗口，每个窗口执行：
mysql -h 8.146.236.55 -P 3306 -u root -p'.My19w2fLC6Ob' -e "SELECT SLEEP(300);"
重复执行多次以创建大量空闲连接
*/


-- ============================================================
-- 第五部分：监控连接状态
-- ============================================================

-- 实时监控连接数变化
SELECT 
    COUNT(*) AS total_connections,
    SUM(CASE WHEN COMMAND = 'Sleep' THEN 1 ELSE 0 END) AS sleeping_connections,
    SUM(CASE WHEN COMMAND != 'Sleep' THEN 1 ELSE 0 END) AS active_connections,
    MAX(TIME) AS longest_connection_time
FROM information_schema.PROCESSLIST;

-- 按用户统计连接数
SELECT 
    USER,
    COUNT(*) AS connection_count,
    GROUP_CONCAT(HOST SEPARATOR ', ') AS hosts
FROM information_schema.PROCESSLIST
GROUP BY USER
ORDER BY connection_count DESC;

-- 按数据库统计连接数
SELECT 
    DB,
    COUNT(*) AS connection_count
FROM information_schema.PROCESSLIST
WHERE DB IS NOT NULL
GROUP BY DB
ORDER BY connection_count DESC;


-- ============================================================
-- 第六部分：连接数限制调整（谨慎使用）
-- ============================================================

-- 查看当前最大连接数
SHOW VARIABLES LIKE 'max_connections';

-- 如果需要临时增加最大连接数（需要SUPER权限）
-- SET GLOBAL max_connections = 200;

-- 恢复默认值（根据MySQL版本不同，默认值可能为151）
-- SET GLOBAL max_connections = 151;


-- ============================================================
-- 第七部分：清理和恢复
-- ============================================================

-- 停止事件调度器
-- ALTER EVENT evt_connection_stress_test DISABLE;

-- 删除事件
-- DROP EVENT IF EXISTS evt_connection_stress_test;

-- 删除存储过程
-- DROP PROCEDURE IF EXISTS simulate_connection_hog;

-- 杀死长时间运行的连接（谨慎使用）
-- SELECT CONCAT('KILL ', ID, ';') AS kill_command
-- FROM information_schema.PROCESSLIST
-- WHERE TIME > 300 AND COMMAND = 'Sleep';


-- ============================================================
-- 第八部分：外部工具辅助测试
-- ============================================================

/*
除了SQL脚本外，还可以使用以下方法进行连接数测试：

1. 使用 mysqlslap 工具：
   mysqlslap --host=8.146.236.55 --port=3306 --user=root --password='.My19w2fLC6Ob' \
   --concurrency=50 --iterations=1 --query="SELECT SLEEP(1)"

2. 使用 Python 脚本创建多个连接：
   import mysql.connector
   import time
   import threading
   
   def create_connection():
       try:
           conn = mysql.connector.connect(
               host='8.146.236.55',
               port=3306,
               user='root',
               password='.My19w2fLC6Ob',
               database='ry-vue'
           )
           cursor = conn.cursor()
           cursor.execute("SELECT SLEEP(300)")  # 保持连接5分钟
           cursor.close()
           conn.close()
       except Exception as e:
           print(f"Connection error: {e}")
   
   # 创建50个并发连接
   threads = []
   for i in range(50):
       t = threading.Thread(target=create_connection)
       t.start()
       threads.append(t)
   
   for t in threads:
       t.join()

3. 使用 Apache Bench 或其他压力测试工具
*/


-- ============================================================
-- 使用说明
-- ============================================================
/*
1. 首先执行第一部分检查当前连接配置
2. 根据需要执行第二部分创建存储过程
3. 可选择执行第三部分创建自动化压力测试事件
4. 执行第五部分监控连接状态变化
5. 如需调整连接限制，谨慎执行第六部分
6. 测试完成后执行第七部分进行清理
7. 可结合第八部分的外部工具进行更全面的测试

注意事项：
- 在生产环境执行前务必备份重要数据
- 连接数打满可能导致服务不可用，请在测试环境执行
- 监控系统资源使用情况，避免影响其他服务
- 记录测试前后的性能指标以便对比分析
- 确保有足够的权限执行这些操作
*/