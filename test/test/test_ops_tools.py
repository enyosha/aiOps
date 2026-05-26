import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import asyncio
from utils.tool_cache import tool_cache

async def test():
    tools = await tool_cache.get_tools('ops-diagnosis')
    print(f'Loaded {len(tools)} tools')
    for t in tools:
        print(f'  - {t.name}')
    
    mem_tool = next((t for t in tools if t.name == 'check_memory_usage'), None)
    if mem_tool:
        result = await mem_tool.ainvoke({})
        print(f'\nResult type: {type(result)}')
        print(f'Result: {result}')

asyncio.run(test())
