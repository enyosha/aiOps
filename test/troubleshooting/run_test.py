"""
统一测试脚本 - 通过问答形式运行指定Case并生成诊断报�?

功能:
1. 交互式选择要测试的Case
2. 自动构建故障环境
3. 调用DiagnosisAgent进行诊断
4. 实时打印诊断过程到Console
5. 保存完整日志�?reports/casexx_YYYYMMDD_HHMMSS.txt
6. 自动恢复环境
7. 生成评估报告
"""
import sys
import os
import asyncio
import logging
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from dotenv import load_dotenv
load_dotenv()


def setup_logger(case_id):
    """
    设置日志记录�?同时输出到Console和文�?
    
    Args:
        case_id: Case编号 (1-5)
    
    Returns:
        tuple: (logger对象, 日志文件路径)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 日志文件相对�?troubleshooting 目录
    log_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"case{case_id}_{timestamp}.txt")
    
    logger = logging.getLogger(f"case{case_id}")
    logger.setLevel(logging.INFO)
    
    # 清除已有的handlers
    logger.handlers.clear()
    
    # 文件handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # 格式化器
    formatter = logging.Formatter('%(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger, log_file


def print_separator(logger, char="=", length=80):
    """打印分隔�?""
    line = char * length
    logger.info(line)


def get_alert_event(case_id):
    """
    根据Case编号构造对应的Grafana告警事件
    
    Args:
        case_id: Case编号 (1-5)
    
    Returns:
        dict: 告警事件数据
    """
    alert_events = {
        1: {
            "alert_name": "Tomcat线程池耗尽",
            "alert_type": "tomcat_thread_pool_exhausted",
            "alert_time": datetime.now().isoformat(),
            "description": "前端请求响应时间显著增加,高并发时部分请求返回504 Gateway Timeout"
        },
        2: {
            "alert_name": "静态资源加载失�?,
            "alert_type": "static_resource_404",
            "alert_time": datetime.now().isoformat(),
            "description": "前端页面样式丢失,CSS/JS文件返回404错误,页面显示异常"
        },
        3: {
            "alert_name": "MySQL连接池耗尽",
            "alert_type": "database_connection_pool_exhausted",
            "alert_time": datetime.now().isoformat(),
            "description": "后端服务响应超时,应用日志显示Cannot get connection from pool"
        },
        4: {
            "alert_name": "",
            "alert_type": "",
            "alert_time": datetime.now().isoformat(),
            "description": ""
        },
        # 4: {
        #     "alert_name": "JVM堆内存溢�?,
        #     "alert_type": "jvm_out_of_memory",
        #     "alert_time": datetime.now().isoformat(),
        #     "description": "应用突然崩溃,容器仍在运行但无法提供服�?日志显示OutOfMemoryError"
        # },
        5: {
            "alert_name": "MySQL慢查询导致CPU飙升",
            "alert_type": "mysql_slow_query_high_cpu",
            "alert_time": datetime.now().isoformat(),
            "description": "系统CPU使用率持�?90%,前端页面加载缓慢,后端接口响应超时"
        }
    }
    
    return alert_events.get(case_id, {
        "alert_name": "未知故障",
        "alert_type": "unknown",
        "alert_time": datetime.now().isoformat(),
        "description": "未知故障类型"
    })


async def run_diagnosis(alert_event, container_name="ruoyi-app"):
    """
    调用DiagnosisAgent进行诊断
    
    Args:
        alert_event: 告警事件数据
        container_name: 容器名称
    
    Returns:
        dict: 诊断结果
    """
    import sys
    from io import StringIO
    
    try:
        from Routing.diagnosis_agent import run_diagnosis as diagnosis_func
        
        print_separator(logger, "-", 80)
        logger.info("🔍 开始调用DiagnosisAgent进行诊断...")
        print_separator(logger, "-", 80)
        
        # 捕获 DiagnosisAgent 的输�?
        old_stdout = sys.stdout
        captured_output = StringIO()
        
        class DualOutput:
            """同时输出到控制台和日志文�?""
            def __init__(self, original_stdout, logger):
                self.original_stdout = original_stdout
                self.logger = logger
                self.buffer = ""
            
            def write(self, text):
                # 写入原始stdout(控制�?
                self.original_stdout.write(text)
                self.original_stdout.flush()
                
                # 记录到logger
                if text.strip():  # 忽略空行
                    self.logger.info(text.rstrip())
            
            def flush(self):
                self.original_stdout.flush()
        
        # 重定向stdout
        sys.stdout = DualOutput(old_stdout, logger)
        
        try:
            result = await diagnosis_func(alert_event, container_name)
        finally:
            # 恢复stdout
            sys.stdout = old_stdout
        
        return result
    except Exception as e:
        logger.error(f"�?诊断失败: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": str(e)
        }


def evaluate_diagnosis(case_id, diagnosis_result):
    """
    评估诊断结果
    
    Args:
        case_id: Case编号
        diagnosis_result: 诊断结果
    
    Returns:
        dict: 评估报告
    """
    evaluation = {
        "accuracy": "N/A",
        "completeness": "N/A",
        "actionability": "N/A",
        "efficiency": "N/A",
        "overall_score": "N/A",
        "comments": []
    }
    
    if diagnosis_result.get("status") != "success":
        evaluation["overall_score"] = "0/10"
        evaluation["comments"].append("诊断执行失败")
        return evaluation
    
    diagnosis = diagnosis_result.get("diagnosis", {})
    content = diagnosis.get("content", "")
    data_sources = diagnosis.get("data_sources", {})
    iteration_count = diagnosis_result.get("iteration_count", 0)
    
    # 准确性评�?
    accuracy_keywords = {
        1: ["tomcat", "thread", "线程", "pool"],
        2: ["404", "static", "资源", "css", "js"],
        3: ["connection pool", "连接�?, "druid", "maxactive"],
        4: ["outofmemory", "oom", "heap", "jvm", "内存溢出"],
        5: ["slow query", "慢查�?, "cpu", "mysql", "索引"]
    }
    
    keywords = accuracy_keywords.get(case_id, [])
    if any(kw.lower() in content.lower() for kw in keywords):
        evaluation["accuracy"] = "�?准确定位问题"
        evaluation["comments"].append(f"正确识别到{keywords[0]}相关关键�?)
    else:
        evaluation["accuracy"] = "�?未准确定�?
        evaluation["comments"].append("未能识别关键故障特征")
    
    # 完整性评�?
    data_collected_count = sum([
        data_sources.get("logs", False),
        data_sources.get("memory", False),
        data_sources.get("cpu", False),
        data_sources.get("service_status", False)
    ])
    
    if data_collected_count >= 2:
        evaluation["completeness"] = f"�?收集了{data_collected_count}类数�?
        evaluation["comments"].append("数据采集较为完整")
    elif data_collected_count == 1:
        evaluation["completeness"] = "�?仅收�?类数�?
        evaluation["comments"].append("建议收集更多数据�?)
    else:
        evaluation["completeness"] = "�?未收集数�?
        evaluation["comments"].append("未能获取任何实时数据")
    
    # 可操作性评�?
    action_keywords = ["docker", "命令", "执行", "修改", "配置", "重启", "`"]
    has_commands = any(kw in content for kw in action_keywords)
    
    if has_commands and ("立即" in content or "建议" in content):
        evaluation["actionability"] = "�?给出具体操作建议"
        evaluation["comments"].append("包含可执行的命令或配置修�?)
    elif has_commands:
        evaluation["actionability"] = "�?有部分建�?
        evaluation["comments"].append("建议不够具体或缺少步�?)
    else:
        evaluation["actionability"] = "�?缺少可操作建�?
        evaluation["comments"].append("未提供具体的修复方案")
    
    # 效率评估
    if iteration_count <= 3:
        evaluation["efficiency"] = f"�?高效({iteration_count}次迭�?"
    elif iteration_count <= 5:
        evaluation["efficiency"] = f"�?一�?{iteration_count}次迭�?"
    else:
        evaluation["efficiency"] = f"�?较慢({iteration_count}次迭�?"
    
    # 总体评分
    scores = []
    if "�? in evaluation["accuracy"]:
        scores.append(3)
    elif "�? in evaluation["accuracy"]:
        scores.append(2)
    else:
        scores.append(0)
    
    if "�? in evaluation["completeness"]:
        scores.append(2)
    elif "�? in evaluation["completeness"]:
        scores.append(1)
    else:
        scores.append(0)
    
    if "�? in evaluation["actionability"]:
        scores.append(3)
    elif "�? in evaluation["actionability"]:
        scores.append(2)
    else:
        scores.append(0)
    
    if "�? in evaluation["efficiency"]:
        scores.append(2)
    elif "�? in evaluation["efficiency"]:
        scores.append(1)
    else:
        scores.append(0)
    
    total_score = sum(scores)
    evaluation["overall_score"] = f"{total_score}/10"
    
    return evaluation


async def test_case(case_id, mode=1):
    """
    测试单个Case的完整流�?
    
    Args:
        case_id: Case编号 (1-5)
        mode: 执行模式
            - 1: 全流�?(Generate �?Test �?Resume)
            - 2: 仅测�?(Test only,跳过Generate)
            - 3: 仅恢�?(Resume only,跳过Generate和Test)
    """
    global logger
    
    # 设置日志
    logger, log_file = setup_logger(case_id)
    
    print_separator(logger)
    logger.info(f"🧪 Case{case_id:02d} 测试开�?)
    logger.info(f"📅 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📄 报告文件: {log_file}")
    print_separator(logger)
    
    # 步骤1: 构建故障环境
    if mode == 1:
        logger.info("\n【阶�?】构建故障环�?)
        print_separator(logger, "-")
        
        try:
            from test.troubleshooting.generateCase import (
                generate_case01, generate_case02, generate_case03,
                generate_case04, generate_case05
            )
            
            case_functions = {
                1: generate_case01,
                2: generate_case02,
                3: generate_case03,
                4: generate_case04,
                5: generate_case05
            }
            
            if case_id in case_functions:
                case_functions[case_id]()
                logger.info("\n�?故障环境构建成功!\n")
            else:
                logger.error(f"�?无效的Case编号: {case_id}")
                return
        except Exception as e:
            logger.error(f"�?故障环境构建失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return
        
        # 中断判断: Generate完成后询问是否继�?
        logger.info("\n" + "="*80)
        logger.info("⚠️  故障环境已构建完�?")
        logger.info("="*80)
        confirm = input("是否继续执行诊断测试? (y/n): ").strip().lower()
        
        if confirm != 'y':
            logger.info("\n⚠️  用户取消测试,建议稍后执行恢复:\n")
            logger.info(f"   python run_test.py --case {case_id} --mode 3")
            logger.info("\n退出测试\n")
            return
    elif mode == 2:
        logger.info("\n【阶�?】跳�?模式2:仅测�?")
        print_separator(logger, "-")
        logger.info("⚠️  请确保故障环境已通过其他方式构建\n")
    elif mode == 3:
        logger.info("\n【阶�?】跳�?模式3:仅恢�?")
        print_separator(logger, "-")
    
    # 等待故障稳定 & 执行测试(仅mode 1�?)
    if mode in [1, 2]:
        logger.info("�?等待30秒让故障现象稳定...")
        import time
        time.sleep(30)
        
        # 步骤2: 构造告警事�?
        logger.info("\n【阶�?】构造告警事�?)
        print_separator(logger, "-")
        
        alert_event = get_alert_event(case_id)
        logger.info(f"告警名称: {alert_event['alert_name']}")
        logger.info(f"告警类型: {alert_event['alert_type']}")
        logger.info(f"告警描述: {alert_event['description']}")
        
        # 步骤3: 调用诊断Agent
        logger.info("\n【阶�?】执行诊�?)
        print_separator(logger, "-")
        
        diagnosis_result = await run_diagnosis(alert_event, "ruoyi-app")
        
        if diagnosis_result.get("status") == "success":
            logger.info("\n�?诊断完成!")
            
            # 打印诊断结果
            diagnosis = diagnosis_result.get("diagnosis", {})
            content = diagnosis.get("content", "")
            
            logger.info("\n【诊断结果�?)
            print_separator(logger, "-")
            logger.info(content)
            
            # 打印数据收集情况
            data_sources = diagnosis.get("data_sources", {})
            logger.info("\n【数据收集情况�?)
            print_separator(logger, "-")
            logger.info(f"日志数据: {'�? if data_sources.get('logs') else '�?}")
            logger.info(f"内存信息: {'�? if data_sources.get('memory') else '�?}")
            logger.info(f"CPU信息: {'�? if data_sources.get('cpu') else '�?}")
            logger.info(f"服务状�? {'�? if data_sources.get('service_status') else '�?}")
            logger.info(f"迭代次数: {diagnosis_result.get('iteration_count', 0)}")
        else:
            logger.error(f"\n�?诊断失败: {diagnosis_result.get('message')}")
        
        # 步骤4: 评估诊断结果
        logger.info("\n【阶�?】评估诊断质�?)
        print_separator(logger, "-")
        
        evaluation = evaluate_diagnosis(case_id, diagnosis_result)
        
        logger.info(f"准确�? {evaluation['accuracy']}")
        logger.info(f"完整�? {evaluation['completeness']}")
        logger.info(f"可操作�? {evaluation['actionability']}")
        logger.info(f"效率: {evaluation['efficiency']}")
        logger.info(f"\n总体评分: {evaluation['overall_score']}")
        
        logger.info("\n【评估意见�?)
        for comment in evaluation['comments']:
            logger.info(f"  �?{comment}")
    elif mode == 3:
        logger.info("【阶�?-4】跳�?模式3:仅恢�?")
        print_separator(logger, "-")
        diagnosis_result = {}  # 空字�?避免后续引用错误
    
    # 步骤5: 恢复环境
    if mode in [1, 3]:
        logger.info("\n【阶�?】恢复环�?)
        print_separator(logger, "-")
        
        try:
            from test.troubleshooting.resumeCase import (
                resume_case01, resume_case02, resume_case03,
                resume_case04, resume_case05
            )
            
            resume_functions = {
                1: resume_case01,
                2: resume_case02,
                3: resume_case03,
                4: resume_case04,
                5: resume_case05
            }
            
            if case_id in resume_functions:
                resume_functions[case_id]()
                logger.info("\n�?环境恢复成功!\n")
            else:
                logger.error(f"�?无效的Case编号: {case_id}")
        except Exception as e:
            logger.error(f"�?环境恢复失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    elif mode == 2:
        logger.info("\n【阶�?】跳�?模式2:仅测�?")
        print_separator(logger, "-")
        logger.info("⚠️  请手动执行恢�?\n")
        logger.info(f"   python run_test.py --case {case_id} --mode 3\n")
    
    # 测试完成
    print_separator(logger)
    logger.info(f"�?Case{case_id:02d} 测试完成!")
    logger.info(f"📄 完整日志已保存到: {log_file}")
    print_separator(logger)


def main():
    """主函�?""
    print("\n" + "="*80)
    print("AI运维诊断Agent - 故障场景测试工具")
    print("="*80)
    
    # 检查命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='运维故障测试工具')
    parser.add_argument('--case', type=int, choices=[1,2,3,4,5], help='Case编号(1-5)')
    parser.add_argument('--mode', type=int, choices=[1,2,3], default=1,
                       help='执行模式: 1=全流�? 2=仅测�? 3=仅恢�?)
    args = parser.parse_args()
    
    if args.case:
        # 命令行指定了case,直接运行
        case_id = args.case
        mode = args.mode
    else:
        # 交互式选择
        print("\n请选择要测试的故障场景:")
        print("-"*80)
        print("1. Tomcat线程池耗尽导致请求超时 (前端�?")
        print("2. 静态资源加载失�?04/403 (前端�?")
        print("3. MySQL连接池耗尽 (后端�?")
        print("4. JVM堆内存溢�?(后端�?")
        print("5. MySQL慢查询导致CPU飙升 (后端�?")
        print("-"*80)
        
        try:
            choice = input("\n请输入Case编号(1-5, 输入q退�?: ").strip()
            
            if choice.lower() == 'q':
                print("退出测�?)
                return
            
            case_id = int(choice)
            
            if case_id not in [1, 2, 3, 4, 5]:
                print("�?无效的Case编号,请输�?-5")
                return
            
            # 选择执行模式
            print("\n请选择执行模式:")
            print("-"*80)
            print("1. 全流�?(Generate �?Test �?Resume)")
            print("2. 仅测�?(Test only,跳过Generate)")
            print("3. 仅恢�?(Resume only,跳过Generate和Test)")
            print("-"*80)
            
            mode_choice = input("\n请输入模式编�?1-3, 默认1): ").strip()
            
            if mode_choice == '':
                mode = 1
            else:
                mode = int(mode_choice)
                
                if mode not in [1, 2, 3]:
                    print("�?无效的模式编�?请输�?-3")
                    return
        except ValueError:
            print("�?无效输入,请输入数�?)
            return
    
    # 显示执行信息
    mode_names = {
        1: "全流�?(Generate �?Test �?Resume)",
        2: "仅测�?(Test only)",
        3: "仅恢�?(Resume only)"
    }
    
    print(f"\n📋 执行计划:")
    print(f"   Case: {case_id}")
    print(f"   模式: {mode} - {mode_names[mode]}")
    print()
    
    # 运行测试
    try:
        asyncio.run(test_case(case_id, mode))
        print("\n�?测试完成!\n")
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断测试")
    except Exception as e:
        print(f"\n�?发生错误: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
