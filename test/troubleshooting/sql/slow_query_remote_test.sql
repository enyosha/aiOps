-- ============================================================
-- 远程数据库连接与慢查询测试脚本
-- 数据库: 8.146.236.55 (Docker MySQL)
-- 用户: root
-- 说明: 此脚本用于在远程数据库上生成测试数据并执行慢查询测试
-- ============================================================

-- ============================================================
-- 使用前准备
-- ============================================================
/*
连接命令示例:
mysql -h 8.146.236.55 -P 3306 -u root -p'.My19w2fLC6Ob'

或者先连接到数据库:
mysql -h 8.146.236.55 -P 3306 -u root -p
(输入密码: .My19w2fLC6Ob)

然后选择数据库:
USE ry-vue;  (或您的实际数据库名)

最后执行此脚本:
source c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/test/troubleshooting/sql/slow_query_remote_test.sql
*/


-- ============================================================
-- 第一步: 确认当前数据库
-- ============================================================
SELECT DATABASE() AS current_database;
SELECT @@hostname AS server_host;
SELECT VERSION() AS mysql_version;


-- ============================================================
-- 第二步: 检查 sys_oper_log 表是否存在
-- ============================================================
SHOW TABLES LIKE 'sys_oper_log';

-- 如果表不存在，需要先执行基础的若依SQL脚本创建表结构
-- source path/to/ry_20260417.sql


-- ============================================================
-- 第三步: 查看当前数据量
-- ============================================================
SELECT 
    COUNT(*) AS total_records,
    MIN(oper_time) AS earliest_record,
    MAX(oper_time) AS latest_record
FROM sys_oper_log;


-- ============================================================
-- 第四步: 生成测试数据（如果需要）
-- ============================================================

-- 检查是否需要生成测试数据（如果记录数少于1000条）
SELECT 
    CASE 
        WHEN COUNT(*) < 1000 THEN '需要生成测试数据'
        ELSE CONCAT('已有 ', COUNT(*), ' 条数据，可跳过生成')
    END AS data_status
FROM sys_oper_log;


-- 如果需要生成测试数据，执行以下存储过程
DELIMITER $$

DROP PROCEDURE IF EXISTS generate_remote_test_data$$

CREATE PROCEDURE generate_remote_test_data(IN target_count INT)
BEGIN
    DECLARE i INT DEFAULT 1;
    DECLARE current_count INT;
    DECLARE v_business_type INT;
    DECLARE v_status INT;
    DECLARE v_oper_name VARCHAR(50);
    DECLARE v_dept_name VARCHAR(50);
    DECLARE v_oper_ip VARCHAR(128);
    DECLARE v_oper_location VARCHAR(255);
    DECLARE v_oper_param VARCHAR(2000);
    DECLARE v_json_result VARCHAR(2000);
    DECLARE v_error_msg VARCHAR(2000);
    DECLARE v_oper_time DATETIME;
    
    -- 获取当前记录数
    SELECT COUNT(*) INTO current_count FROM sys_oper_log;
    
    IF current_count >= target_count THEN
        SELECT CONCAT('已有 ', current_count, ' 条数据，无需生成') AS result;
    ELSE
        SET i = current_count + 1;
        SET v_oper_time = DATE_SUB(NOW(), INTERVAL 365 DAY);
        
        SELECT CONCAT('开始生成数据，从第 ', i, ' 条到第 ', target_count, ' 条') AS result;
        
        WHILE i <= target_count DO
            SET v_business_type = FLOOR(RAND() * 10);
            SET v_status = IF(RAND() > 0.95, 1, 0);
            SET v_oper_name = ELT(FLOOR(RAND() * 5) + 1, 'admin', 'ry', 'test_user', 'operator1', 'operator2');
            SET v_dept_name = ELT(FLOOR(RAND() * 10) + 1, 
                '研发部门', '市场部门', '测试部门', '财务部门', '运维部门',
                '深圳总公司', '长沙分公司', '人力资源部', '产品部', '客服部');
            SET v_oper_ip = CONCAT(
                FLOOR(RAND() * 255), '.',
                FLOOR(RAND() * 255), '.',
                FLOOR(RAND() * 255), '.',
                FLOOR(RAND() * 255)
            );
            SET v_oper_location = ELT(FLOOR(RAND() * 10) + 1,
                '广东省深圳市', '湖南省长沙市', '北京市', '上海市', '广州市',
                '杭州市', '成都市', '武汉市', '南京市', '西安市');
            
            SET v_oper_param = CONCAT(
                '{"userId":', FLOOR(RAND() * 10000), 
                ',"userName":"user_', LPAD(i, 6, '0'),
                '","email":"user_', LPAD(i, 6, '0'), '@example.com",',
                '"phoneNumber":"138', LPAD(FLOOR(RAND() * 100000000), 8, '0'), '",',
                '"sex":"', IF(RAND() > 0.5, '0', '1'), '",',
                '"deptId":', FLOOR(RAND() * 200), ',',
                '"postIds":[', FLOOR(RAND() * 10), ',', FLOOR(RAND() * 10), '],',
                '"roleIds":[', FLOOR(RAND() * 5), ',', FLOOR(RAND() * 5), '],',
                '"remark":"测试数据第', i, '条"}'
            );
            
            SET v_json_result = CONCAT(
                '{"code":200,"msg":"操作成功","data":{"id":', FLOOR(RAND() * 100000), '}}'
            );
            
            IF v_status = 1 THEN
                SET v_error_msg = CONCAT('操作失败：错误代码 ERR_', FLOOR(RAND() * 10000));
            ELSE
                SET v_error_msg = '';
            END IF;
            
            INSERT INTO sys_oper_log (
                title, business_type, method, request_method, operator_type,
                oper_name, dept_name, oper_url, oper_ip, oper_location,
                oper_param, json_result, status, error_msg, oper_time, cost_time
            ) VALUES (
                ELT(FLOOR(RAND() * 15) + 1,
                    '用户管理', '角色管理', '菜单管理', '部门管理', '岗位管理',
                    '字典管理', '参数设置', '通知公告', '操作日志', '登录日志',
                    '在线用户', '定时任务', '代码生成', '服务监控', '缓存监控'),
                v_business_type,
                CONCAT('com.ruoyi.web.controller.system.SysUserServiceImpl.', 
                    ELT(FLOOR(RAND() * 4) + 1, 'list', 'add', 'edit', 'remove')),
                ELT(FLOOR(RAND() * 3) + 1, 'GET', 'POST', 'PUT'),
                FLOOR(RAND() * 3),
                v_oper_name,
                v_dept_name,
                CONCAT('/system/user/', ELT(FLOOR(RAND() * 4) + 1, 'list', 'add', 'edit', 'remove')),
                v_oper_ip,
                v_oper_location,
                v_oper_param,
                v_json_result,
                v_status,
                v_error_msg,
                v_oper_time,
                FLOOR(RAND() * 5000)
            );
            
            SET i = i + 1;
            SET v_oper_time = DATE_ADD(v_oper_time, INTERVAL FLOOR(RAND() * 300) SECOND);
            
            IF i % 1000 = 0 THEN
                COMMIT;
            END IF;
            
        END WHILE;
        
        COMMIT;
        SELECT CONCAT('成功生成测试数据，总计 ', i - 1, ' 条') AS result;
    END IF;
END$$

DELIMITER ;

-- 执行生成 10000 条测试数据（可根据需要调整数量）
CALL generate_remote_test_data(10000);

-- 清理存储过程
DROP PROCEDURE IF EXISTS generate_remote_test_data;


-- ============================================================
-- 第五步: 验证数据生成结果
-- ============================================================
SELECT 
    COUNT(*) AS total_records,
    MIN(oper_time) AS earliest_record,
    MAX(oper_time) AS latest_record,
    COUNT(DISTINCT oper_name) AS unique_users,
    COUNT(DISTINCT oper_ip) AS unique_ips
FROM sys_oper_log;


-- ============================================================
-- 第六步: 执行慢查询测试
-- ============================================================

-- 慢查询测试 1: 模糊查询（最典型的慢查询）
SELECT '=== 慢查询测试 1: 模糊查询 ===' AS test_name;
SELECT 
    oper_id,
    oper_name,
    oper_time,
    LEFT(oper_param, 100) AS param_preview
FROM sys_oper_log
WHERE oper_param LIKE '%"userName":"user_001234"%'
ORDER BY oper_time DESC
LIMIT 10;


-- 慢查询测试 2: 函数过滤导致索引失效
SELECT '=== 慢查询测试 2: 函数过滤 ===' AS test_name;
SELECT 
    DATE_FORMAT(oper_time, '%Y-%m-%d') AS oper_date,
    COUNT(*) AS daily_count
FROM sys_oper_log
WHERE DATE_FORMAT(oper_time, '%Y-%m-%d') = DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 100 DAY), '%Y-%m-%d')
GROUP BY DATE_FORMAT(oper_time, '%Y-%m-%d');


-- 慢查询测试 3: OR 条件查询
SELECT '=== 慢查询测试 3: OR条件查询 ===' AS test_name;
SELECT 
    oper_id,
    oper_name,
    oper_ip,
    oper_time
FROM sys_oper_log
WHERE oper_name = 'admin'
   OR oper_ip LIKE '192.168.%'
   OR oper_location = '广东省深圳市'
ORDER BY oper_time DESC
LIMIT 100;


-- 慢查询测试 4: 大文本字段排序
SELECT '=== 慢查询测试 4: 大文本排序 ===' AS test_name;
SELECT 
    LEFT(oper_param, 50) AS param_preview,
    COUNT(*) AS count,
    AVG(cost_time) AS avg_cost_time
FROM sys_oper_log
WHERE business_type = 1
GROUP BY oper_param
ORDER BY avg_cost_time DESC
LIMIT 20;


-- 慢查询测试 5: 相关子查询（性能最差）
SELECT '=== 慢查询测试 5: 相关子查询 ===' AS test_name;
SELECT 
    o1.oper_id,
    o1.oper_name,
    o1.oper_time,
    o1.cost_time,
    (SELECT AVG(o2.cost_time) 
     FROM sys_oper_log o2 
     WHERE o2.oper_name = o1.oper_name 
       AND o2.oper_time >= DATE_SUB(o1.oper_time, INTERVAL 1 HOUR)
       AND o2.oper_time <= o1.oper_time) AS avg_recent_cost
FROM sys_oper_log o1
WHERE o1.status = 1
  AND o1.oper_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY o1.cost_time DESC
LIMIT 10;


-- 慢查询测试 6: 大范围查询 + 排序
SELECT '=== 慢查询测试 6: 范围查询+排序 ===' AS test_name;
SELECT 
    oper_id,
    title,
    oper_name,
    oper_time,
    cost_time
FROM sys_oper_log
WHERE oper_time BETWEEN DATE_SUB(NOW(), INTERVAL 30 DAY) AND NOW()
  AND business_type IN (1, 2, 3)
  AND status = 0
ORDER BY cost_time DESC
LIMIT 100;


-- ============================================================
-- 第七步: 使用 EXPLAIN 分析查询计划
-- ============================================================

SELECT '=== EXPLAIN 分析 1: 模糊查询 ===' AS analysis;
EXPLAIN SELECT 
    oper_id,
    oper_name,
    oper_time
FROM sys_oper_log
WHERE oper_param LIKE '%"userName":"user_001234"%'
ORDER BY oper_time DESC
LIMIT 10;


SELECT '=== EXPLAIN 分析 2: 范围查询 ===' AS analysis;
EXPLAIN SELECT 
    oper_id,
    oper_name,
    oper_time,
    cost_time
FROM sys_oper_log
WHERE oper_time BETWEEN DATE_SUB(NOW(), INTERVAL 30 DAY) AND NOW()
  AND business_type IN (1, 2, 3)
ORDER BY cost_time DESC
LIMIT 100;


-- ============================================================
-- 第八步: 查看当前索引情况
-- ============================================================
SELECT '=== 当前索引情况 ===' AS info;
SHOW INDEX FROM sys_oper_log;


-- ============================================================
-- 第九步: 添加优化索引（可选）
-- ============================================================

-- 注意：在生产环境添加索引前请评估影响
-- 以下索引仅用于测试和演示

-- 索引 1: 时间和状态复合索引
ALTER TABLE sys_oper_log ADD INDEX idx_time_status (oper_time, status);

-- 索引 2: 操作人员和时间
ALTER TABLE sys_oper_log ADD INDEX idx_name_time (oper_name, oper_time);

-- 索引 3: 业务类型和时间
ALTER TABLE sys_oper_log ADD INDEX idx_type_time (business_type, oper_time);


-- ============================================================
-- 第十步: 测试优化后的查询性能
-- ============================================================

-- 优化查询 1: 使用范围查询代替函数
SELECT '=== 优化查询 1: 范围查询 ===' AS optimized_test;
SELECT 
    oper_name,
    COUNT(*) AS count
FROM sys_oper_log
WHERE oper_time >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 100 DAY), '%Y-%m-%d 00:00:00')
  AND oper_time < DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 99 DAY), '%Y-%m-%d 00:00:00')
GROUP BY oper_name;


-- 优化查询 2: 使用 UNION 代替 OR
SELECT '=== 优化查询 2: UNION代替OR ===' AS optimized_test;
(SELECT oper_id, oper_name, oper_ip, oper_time FROM sys_oper_log WHERE oper_name = 'admin')
UNION ALL
(SELECT oper_id, oper_name, oper_ip, oper_time FROM sys_oper_log WHERE oper_ip LIKE '192.168.%')
UNION ALL
(SELECT oper_id, oper_name, oper_ip, oper_time FROM sys_oper_log WHERE oper_location = '广东省深圳市')
ORDER BY oper_time DESC
LIMIT 100;


-- ============================================================
-- 第十一步: 性能对比总结
-- ============================================================
SELECT '=== 性能测试完成 ===' AS summary;
SELECT 
    COUNT(*) AS total_records,
    COUNT(DISTINCT oper_name) AS unique_operators,
    COUNT(DISTINCT business_type) AS business_types,
    MIN(oper_time) AS date_from,
    MAX(oper_time) AS date_to,
    ROUND(TIMESTAMPDIFF(HOUR, MIN(oper_time), MAX(oper_time)) / 24, 0) AS days_span
FROM sys_oper_log;


-- ============================================================
-- 第十二步: 清理（可选）
-- ============================================================

-- 如需删除测试生成的索引，取消以下注释
-- ALTER TABLE sys_oper_log DROP INDEX idx_time_status;
-- ALTER TABLE sys_oper_log DROP INDEX idx_name_time;
-- ALTER TABLE sys_oper_log DROP INDEX idx_type_time;

-- 如需清空测试数据，取消以下注释（谨慎操作！）
-- TRUNCATE TABLE sys_oper_log;


-- ============================================================
-- 使用说明
-- ============================================================
/*
执行步骤:

1. 连接到远程数据库:
   mysql -h 8.146.236.55 -P 3306 -u root -p'.My19w2fLC6Ob'

2. 选择数据库:
   USE ry-vue;  (替换为实际数据库名)

3. 执行脚本:
   source c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/test/troubleshooting/sql/slow_query_remote_test.sql

4. 观察每个测试的输出和执行时间

5. 查看 EXPLAIN 分析结果，理解查询计划

6. 根据需要添加索引并重新测试

注意事项:
- 首次执行会生成测试数据，可能需要几分钟
- 可以根据需要调整生成数据的数量（修改 CALL 语句中的参数）
- 生产环境执行前务必备份数据
- 添加索引会影响写入性能，请谨慎操作
- 测试完成后可选择清理测试数据和索引
*/
