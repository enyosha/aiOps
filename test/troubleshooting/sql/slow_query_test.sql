-- ============================================================
-- 慢查询测试脚本 - 基于若依框架数据库结构
-- 用途：生成大量测试数据并演示慢查询场景
-- 作者：AiOps 测试团队
-- 日期：2026-05-14
-- ============================================================

-- ============================================================
-- 第一部分：生成大量测试数据
-- ============================================================

-- 1. 清空现有测试数据（可选，谨慎使用）
-- TRUNCATE TABLE sys_oper_log;

-- 2. 使用存储过程生成 100,000 条操作日志记录
DELIMITER $$

DROP PROCEDURE IF EXISTS generate_slow_query_test_data$$

CREATE PROCEDURE generate_slow_query_test_data()
BEGIN
    DECLARE i INT DEFAULT 1;
    DECLARE v_oper_id BIGINT;
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
    
    -- 设置起始时间
    SET v_oper_time = DATE_SUB(NOW(), INTERVAL 365 DAY);
    
    WHILE i <= 100000 DO
        -- 随机生成业务类型 (0-9)
        SET v_business_type = FLOOR(RAND() * 10);
        
        -- 随机生成状态 (0或1)
        SET v_status = IF(RAND() > 0.95, 1, 0);
        
        -- 随机选择操作人员
        SET v_oper_name = ELT(FLOOR(RAND() * 5) + 1, 'admin', 'ry', 'test_user', 'operator1', 'operator2');
        
        -- 随机选择部门
        SET v_dept_name = ELT(FLOOR(RAND() * 10) + 1, 
            '研发部门', '市场部门', '测试部门', '财务部门', '运维部门',
            '深圳总公司', '长沙分公司', '人力资源部', '产品部', '客服部');
        
        -- 随机生成IP地址
        SET v_oper_ip = CONCAT(
            FLOOR(RAND() * 255), '.',
            FLOOR(RAND() * 255), '.',
            FLOOR(RAND() * 255), '.',
            FLOOR(RAND() * 255)
        );
        
        -- 随机生成地点
        SET v_oper_location = ELT(FLOOR(RAND() * 10) + 1,
            '广东省深圳市', '湖南省长沙市', '北京市', '上海市', '广州市',
            '杭州市', '成都市', '武汉市', '南京市', '西安市');
        
        -- 生成较长的操作参数（模拟复杂请求）
        SET v_oper_param = CONCAT(
            '{"userId":', FLOOR(RAND() * 10000), 
            ',"userName":"user_', LPAD(i, 6, '0'),
            '","email":"user_', LPAD(i, 6, '0'), '@example.com",',
            '"phoneNumber":"138', LPAD(FLOOR(RAND() * 100000000), 8, '0'), '",',
            '"sex":"', IF(RAND() > 0.5, '0', '1'), '",',
            '"deptId":', FLOOR(RAND() * 200), ',',
            '"postIds":[', FLOOR(RAND() * 10), ',', FLOOR(RAND() * 10), '],',
            '"roleIds":[', FLOOR(RAND() * 5), ',', FLOOR(RAND() * 5), '],',
            '"remark":"这是第', i, '条测试数据的备注信息，用于模拟真实业务场景中的长文本内容。',
            '在实际系统中，这里可能包含用户的详细描述、特殊要求或其他相关信息。',
            '为了制造慢查询，我们需要让每条记录都包含足够多的数据。"}'
        );
        
        -- 生成JSON结果
        SET v_json_result = CONCAT(
            '{"code":200,"msg":"操作成功","data":{"id":', FLOOR(RAND() * 100000), 
            ',"createTime":"', DATE_FORMAT(v_oper_time, '%Y-%m-%d %H:%i:%s'), 
            '","updateTime":"', DATE_FORMAT(DATE_ADD(v_oper_time, INTERVAL RAND() * 3600 SECOND), '%Y-%m-%d %H:%i:%s'), 
            '"}}'
        );
        
        -- 如果状态为失败，生成错误信息
        IF v_status = 1 THEN
            SET v_error_msg = CONCAT(
                '操作失败：系统异常，错误代码：ERR_', FLOOR(RAND() * 10000), 
                '，详细信息：在处理用户请求时发生未知错误，请检查系统日志获取更多信息。',
                '堆栈跟踪：com.ruoyi.common.exception.ServiceException: 业务处理异常\n',
                '\tat com.ruoyi.system.service.impl.SysUserServiceImpl.insertUser(SysUserServiceImpl.java:123)\n',
                '\tat com.ruoyi.web.controller.system.SysUserController.add(SysUserController.java:89)\n',
                '\tat sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)\n',
                '\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)'
            );
        ELSE
            SET v_error_msg = '';
        END IF;
        
        -- 插入记录
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
            CONCAT('com.ruoyi.web.controller.system.Sys', 
                ELT(FLOOR(RAND() * 5) + 1, 'User', 'Role', 'Menu', 'Dept', 'Post'), 
                'Controller.', 
                ELT(FLOOR(RAND() * 4) + 1, 'list', 'add', 'edit', 'remove')),
            ELT(FLOOR(RAND() * 3) + 1, 'GET', 'POST', 'PUT'),
            FLOOR(RAND() * 3),
            v_oper_name,
            v_dept_name,
            CONCAT('/system/', 
                ELT(FLOOR(RAND() * 10) + 1,
                    'user', 'role', 'menu', 'dept', 'post', 'dict', 'config', 'notice', 'operlog', 'logininfor'),
                '/', 
                ELT(FLOOR(RAND() * 4) + 1, 'list', 'add', 'edit', 'remove')),
            v_oper_ip,
            v_oper_location,
            v_oper_param,
            v_json_result,
            v_status,
            v_error_msg,
            v_oper_time,
            FLOOR(RAND() * 5000)  -- 消耗时间 0-5000ms
        );
        
        -- 递增计数器
        SET i = i + 1;
        
        -- 每次增加随机秒数（模拟不同时间的操作）
        SET v_oper_time = DATE_ADD(v_oper_time, INTERVAL FLOOR(RAND() * 300) SECOND);
        
        -- 每1000条提交一次，避免事务过大
        IF i % 1000 = 0 THEN
            COMMIT;
        END IF;
        
    END WHILE;
    
    COMMIT;
    
    SELECT CONCAT('成功生成 ', i - 1, ' 条测试数据') AS result;
END$$

DELIMITER ;

-- 执行存储过程生成测试数据
CALL generate_slow_query_test_data();

-- 删除存储过程（清理）
DROP PROCEDURE IF EXISTS generate_slow_query_test_data;


-- ============================================================
-- 第二部分：慢查询示例
-- ============================================================

-- 慢查询 1: 模糊查询操作参数（无法使用索引）
-- 问题：LIKE '%xxx%' 前导通配符导致全表扫描
SELECT 
    oper_id,
    oper_name,
    oper_time,
    oper_param
FROM sys_oper_log
WHERE oper_param LIKE '%"userName":"user_001234"%'
ORDER BY oper_time DESC
LIMIT 10;


-- 慢查询 2: 对函数结果进行过滤（无法使用索引）
-- 问题：DATE_FORMAT 函数导致索引失效
SELECT 
    oper_id,
    oper_name,
    DATE_FORMAT(oper_time, '%Y-%m-%d') AS oper_date,
    COUNT(*) AS daily_count
FROM sys_oper_log
WHERE DATE_FORMAT(oper_time, '%Y-%m-%d') = '2026-01-15'
GROUP BY DATE_FORMAT(oper_time, '%Y-%m-%d');


-- 慢查询 3: 多条件OR查询（索引利用不佳）
-- 问题：多个OR条件可能导致索引合并或全表扫描
SELECT 
    oper_id,
    oper_name,
    oper_ip,
    oper_time,
    status
FROM sys_oper_log
WHERE oper_name = 'admin'
   OR oper_ip = '192.168.1.100'
   OR oper_location = '广东省深圳市'
ORDER BY oper_time DESC
LIMIT 100;


-- 慢查询 4: 大文本字段的排序和分组
-- 问题：对大文本字段进行排序需要大量内存和临时表
SELECT 
    SUBSTRING(oper_param, 1, 100) AS param_preview,
    COUNT(*) AS count,
    AVG(cost_time) AS avg_cost_time
FROM sys_oper_log
WHERE business_type = 1
GROUP BY oper_param
ORDER BY avg_cost_time DESC
LIMIT 20;


-- 慢查询 5: 复杂的子查询和相关子查询
-- 问题：相关子查询对每一行都执行一次内部查询
SELECT 
    o1.oper_id,
    o1.oper_name,
    o1.oper_time,
    o1.cost_time,
    (SELECT AVG(o2.cost_time) 
     FROM sys_oper_log o2 
     WHERE o2.oper_name = o1.oper_name 
       AND o2.oper_time >= DATE_SUB(o1.oper_time, INTERVAL 1 HOUR)
       AND o2.oper_time <= o1.oper_time) AS avg_recent_cost_time
FROM sys_oper_log o1
WHERE o1.status = 1
  AND o1.oper_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY o1.cost_time DESC
LIMIT 50;


-- 慢查询 6: 没有适当索引的范围查询 + 排序
-- 问题：大范围查询加上排序会导致文件排序(filesort)
SELECT 
    oper_id,
    title,
    oper_name,
    oper_time,
    cost_time,
    oper_param
FROM sys_oper_log
WHERE oper_time BETWEEN DATE_SUB(NOW(), INTERVAL 30 DAY) AND NOW()
  AND business_type IN (1, 2, 3)
  AND status = 0
ORDER BY cost_time DESC
LIMIT 100;


-- 慢查询 7: JSON 字段提取和过滤（MySQL 5.7+）
-- 问题：JSON_EXTRACT 函数无法有效使用传统索引
SELECT 
    oper_id,
    oper_name,
    oper_time,
    JSON_EXTRACT(oper_param, '$.userId') AS user_id,
    JSON_EXTRACT(oper_param, '$.userName') AS user_name
FROM sys_oper_log
WHERE JSON_EXTRACT(oper_param, '$.deptId') > 100
  AND JSON_EXTRACT(oper_param, '$.sex') = '0'
ORDER BY oper_time DESC
LIMIT 50;


-- 慢查询 8: 跨表关联查询（如果有关联表）
-- 问题：大表JOIN且连接条件没有索引
SELECT 
    o.oper_id,
    o.oper_name,
    u.nick_name,
    d.dept_name,
    o.oper_time,
    o.cost_time
FROM sys_oper_log o
LEFT JOIN sys_user u ON o.oper_name = u.user_name
LEFT JOIN sys_dept d ON u.dept_id = d.dept_id
WHERE o.oper_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
  AND o.business_type = 1
ORDER BY o.cost_time DESC
LIMIT 100;


-- ============================================================
-- 第三部分：优化建议对比查询
-- ============================================================

-- 优化后的查询 1: 使用前缀匹配代替模糊查询
-- 如果知道用户名的前缀，可以使用 LIKE 'user_001234%'
SELECT 
    oper_id,
    oper_name,
    oper_time,
    oper_param
FROM sys_oper_log
WHERE oper_param LIKE '%"userName":"user_001234%'
ORDER BY oper_time DESC
LIMIT 10;


-- 优化后的查询 2: 直接使用范围查询代替函数
SELECT 
    oper_id,
    oper_name,
    COUNT(*) AS daily_count
FROM sys_oper_log
WHERE oper_time >= '2026-01-15 00:00:00'
  AND oper_time < '2026-01-16 00:00:00'
GROUP BY oper_name;


-- 优化后的查询 3: 使用 UNION 代替 OR
SELECT 
    oper_id,
    oper_name,
    oper_ip,
    oper_time,
    status
FROM sys_oper_log
WHERE oper_name = 'admin'

UNION ALL

SELECT 
    oper_id,
    oper_name,
    oper_ip,
    oper_time,
    status
FROM sys_oper_log
WHERE oper_ip = '192.168.1.100'

UNION ALL

SELECT 
    oper_id,
    oper_name,
    oper_ip,
    oper_time,
    status
FROM sys_oper_log
WHERE oper_location = '广东省深圳市'

ORDER BY oper_time DESC
LIMIT 100;


-- ============================================================
-- 第四部分：性能分析工具
-- ============================================================

-- 启用慢查询日志分析
SHOW VARIABLES LIKE 'slow_query_log';
SHOW VARIABLES LIKE 'long_query_time';
SHOW VARIABLES LIKE 'slow_query_log_file';

-- 查看当前表的索引情况
SHOW INDEX FROM sys_oper_log;

-- 分析查询执行计划（在慢查询前加 EXPLAIN）
EXPLAIN SELECT 
    oper_id,
    oper_name,
    oper_time,
    oper_param
FROM sys_oper_log
WHERE oper_param LIKE '%"userName":"user_001234"%'
ORDER BY oper_time DESC
LIMIT 10;


-- ============================================================
-- 第五部分：推荐的索引优化
-- ============================================================

-- 建议添加的索引（根据实际情况选择）

-- 1. 复合索引：针对常见的查询模式
ALTER TABLE sys_oper_log 
ADD INDEX idx_oper_time_status (oper_time, status);

-- 2. 复合索引：针对操作人员和时间查询
ALTER TABLE sys_oper_log 
ADD INDEX idx_oper_name_time (oper_name, oper_time);

-- 3. 索引：针对业务类型查询
ALTER TABLE sys_oper_log 
ADD INDEX idx_business_type_time (business_type, oper_time);

-- 4. 覆盖索引：针对特定查询场景
ALTER TABLE sys_oper_log 
ADD INDEX idx_covering_query (oper_time, oper_name, status, cost_time);


-- ============================================================
-- 第六部分：清理测试数据（可选）
-- ============================================================

-- 如需清理测试数据，取消以下注释
-- TRUNCATE TABLE sys_oper_log;
-- ALTER TABLE sys_oper_log AUTO_INCREMENT = 1;

-- 删除测试添加的索引（如果需要回滚）
-- ALTER TABLE sys_oper_log DROP INDEX idx_oper_time_status;
-- ALTER TABLE sys_oper_log DROP INDEX idx_oper_name_time;
-- ALTER TABLE sys_oper_log DROP INDEX idx_business_type_time;
-- ALTER TABLE sys_oper_log DROP INDEX idx_covering_query;


-- ============================================================
-- 使用说明
-- ============================================================
/*
1. 执行第一部分生成测试数据（约需几分钟到十几分钟，取决于服务器性能）
2. 运行第二部分的慢查询示例，观察执行时间
3. 使用 EXPLAIN 分析查询计划
4. 尝试第三部分的优化查询，对比性能差异
5. 根据需要添加第四部分建议的索引
6. 测试完成后，可选择第六部分清理数据

注意事项：
- 在生产环境执行前务必备份数据
- 生成10万条数据可能需要较长时间和磁盘空间
- 可以根据需要调整生成的数据量（修改 WHILE 循环的上限）
- 建议在测试环境中执行此脚本
*/
