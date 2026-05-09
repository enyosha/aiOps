import re

def filter_log_debug(input_path: str, output_path: str):
    """过滤日志文件中的FastMCP横幅和Uvicorn INFO信息（调试版）"""
    
    with open(input_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
        lines = f.readlines()
    
    filtered_lines = []
    in_banner = False
    info_pattern = re.compile(r'^INFO:\s+\d+\.\d+\.\d+\.\d+:\d+\s+-\s+"GET /api/diagnose/')
    skipped_count = 0
    
    for i, line in enumerate(lines, 1):
        # 检测横幅开始（包含边框的行）
        if '+-----------------------------------------------------------------------------+' in line:
            in_banner = True
            print(f"行 {i}: 检测到横幅开始")
            continue
        
        # 如果在横幅中，跳过直到横幅结束
        if in_banner:
            # 检测横幅结束
            if '+-----------------------------------------------------------------------------+' in line:
                in_banner = False
                print(f"行 {i}: 检测到横幅结束")
            else:
                skipped_count += 1
            continue
        
        # 过滤Uvicorn的GET请求INFO日志（诊断状态查询）
        if info_pattern.match(line):
            skipped_count += 1
            continue
        
        # 保留其他行
        filtered_lines.append(line)
    
    # 写入过滤后的内容
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.writelines(filtered_lines)
    
    print(f"\n统计信息:")
    print(f"原始行数: {len(lines)}")
    print(f"过滤后行数: {len(filtered_lines)}")
    print(f"移除行数: {len(lines) - len(filtered_lines)}")
    print(f"输出文件: {output_path}")

if __name__ == "__main__":
    input_file = "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/logs/api_server_test_20260508184721.log"
    output_file = "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/logs/api_server_test_20260508184721_filtered.log"
    
    filter_log_debug(input_file, output_file)
