import asyncio
import os
from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle

# 加载环境变量
load_dotenv()


async def main():
    """
    使用 Google Gemini 作为 LLM 的 browser-use Agent 示例
    """
    # 检查 API Key
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("请在 .env 文件中设置 GOOGLE_API_KEY")

    # 初始化 Google Gemini 模型
    llm = ChatGoogle(model="gemini-flash-latest")
    task = "搜索 Python 最新版本并告诉我"
    agent = Agent(task=task, llm=llm)


    # 运行 Agent
    result = await agent.run()

    print("\n=== Agent 执行结果 ===")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
