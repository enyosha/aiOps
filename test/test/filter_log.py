import re
from pathlib import Path

def filter_log(input_path: str, output_path: str):
    """过滤日志文件中的FastMCP横幅和Uvicorn INFO信息"""
    
    with open(input_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
        lines = f.readlines()
    
    filtered_lines = []
    in_banner = False
    info_pattern = re.compile(r'^INFO:\s+\d+\.\d+\.\d+\.\d+:\d+\s+-\s+"GET /api/diagnose/')
    
    for line in lines:
        # 检测横幅边界（包含边框的行�?
        if '+-----------------------------------------------------------------------------+' in line:
            # 切换横幅状�?
            in_banner = not in_banner
            continue
        
        # 如果在横幅中，跳�?
        if in_banner:
            continue
        
        # 过滤Uvicorn的GET请求INFO日志（诊断状态查询）
        if info_pattern.match(line):
            continue
        
        # 保留其他�?
        filtered_lines.append(line)
    
    # 写入过滤后的内容
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.writelines(filtered_lines)
    
    print(f"原始行数: {len(lines)}")
    print(f"过滤后行�? {len(filtered_lines)}")
    print(f"移除行数: {len(lines) - len(filtered_lines)}")
    print(f"输出文件: {output_path}")

if __name__ == "__main__":
    input_file = "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/logs/api_server_test_20260508184721.log"
    output_file = "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/logs/api_server_test_20260508184721_filtered.log"
    
    filter_log(input_file, output_file)
