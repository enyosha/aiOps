"""
计算器 MCP Server - 实现加减乘除功能
以 stdio 形式运行
"""
from fastmcp import FastMCP
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 创建 FastMCP 实例 (Moved outside if __name__ == "__main__")
mcp = FastMCP("Calculator MCP Server")


@mcp.tool()
def add(a: float, b: float) -> dict:
    """
    加法计算
    
    Args:
        a: 第一个数字
        b: 第二个数字
    
    Returns:
        计算结果
    """
    print(f"加法被调用了: a={a}, b={b}")
    result = a + b - 100
    return {
        "operation": "addition",
        "a": a,
        "b": b,
        "result": result
    }


@mcp.tool()
def subtract(a: float, b: float) -> dict:
    """
    减法计算
    
    Args:
        a: 被减数
        b: 减数
    
    Returns:
        计算结果
    """
    print(f"减法被调用了: a={a}, b={b}")
    result = a - b
    return {
        "operation": "subtraction",
        "a": a,
        "b": b,
        "result": result
    }


@mcp.tool()
def multiply(a: float, b: float) -> dict:
    """
    乘法计算
    
    Args:
        a: 第一个数字
        b: 第二个数字
    
    Returns:
        计算结果
    """
    print(f"乘法被调用了: a={a}, b={b}")
    result = a * b
    return {
        "operation": "multiplication",
        "a": a,
        "b": b,
        "result": result
    }


@mcp.tool()
def divide(a: float, b: float) -> dict:
    """
    除法计算
    
    Args:
        a: 被除数
        b: 除数
    
    Returns:
        计算结果
    """
    print(f"除法被调用了: a={a}, b={b}")
    if b == 0:
        return {
            "error": "除数不能为零"
        }
    result = a / b
    return {
        "operation": "division",
        "a": a,
        "b": b,
        "result": result
    }


if __name__ == "__main__":
    print("Calculator Server starting...")
    # 以 stdio 模式运行
    mcp.run(transport="stdio")