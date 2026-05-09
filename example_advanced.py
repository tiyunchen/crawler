import asyncio
import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig

# 加载环境变量
load_dotenv()


async def advanced_example():
    """
    高级示例：带有自定义配置的 browser-use Agent
    """
    # 检查 API Key
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("请在 .env 文件中设置 GOOGLE_API_KEY")
    
    # 初始化 Google Gemini 模型
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        google_api_key=api_key,
        temperature=0.5,
    )
    
    # 配置浏览器
    browser_config = BrowserConfig(
        headless=False,  # 显示浏览器窗口
        disable_security=True,  # 禁用安全限制（仅用于开发）
    )
    
    # 创建浏览器实例
    browser = Browser(config=browser_config)
    
    # 创建控制器
    controller = Controller()
    
    # 创建 Agent
    agent = Agent(
        task="打开 GitHub，搜索 browser-use 项目，并告诉我它有多少个 star",
        llm=llm,
        browser=browser,
        controller=controller,
    )
    
    # 运行 Agent
    result = await agent.run()
    
    print("\n=== Agent 执行结果 ===")
    print(result)


async def multi_step_example():
    """
    多步骤任务示例
    """
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("请在 .env 文件中设置 GOOGLE_API_KEY")
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-exp",
        google_api_key=api_key,
        temperature=0.7,
    )
    
    # 定义复杂任务
    task = """
    1. 打开百度
    2. 搜索"人工智能最新发展"
    3. 查看前3个搜索结果的标题
    4. 总结这些标题的主题
    """
    
    agent = Agent(
        task=task,
        llm=llm,
    )
    
    result = await agent.run()
    
    print("\n=== 多步骤任务结果 ===")
    print(result)


if __name__ == "__main__":
    print("选择示例:")
    print("1. 高级配置示例")
    print("2. 多步骤任务示例")
    
    choice = input("请输入选项 (1 或 2): ")
    
    if choice == "1":
        asyncio.run(advanced_example())
    elif choice == "2":
        asyncio.run(multi_step_example())
    else:
        print("无效选项")
