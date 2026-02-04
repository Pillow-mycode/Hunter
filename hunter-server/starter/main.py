import os
import json
from dotenv import load_dotenv
load_dotenv()

from agent.pojo.leader_config import AttackLeaderConfig
from agent.smart_brain.attack_leader import AttackLeader
from agent.system.system_command import write_to_logs

"""
Hunter 启动入口
通过渗透专家执行渗透测试
"""


def main(user_command: str):
    """
    主函数 - CLI模式

    Args:
        user_command: 用户命令
    """
    print("="*60)
    print("Hunter 自动化渗透测试系统")
    print("="*60)

    # 创建渗透专家
    config = AttackLeaderConfig()
    leader = AttackLeader(config)

    # 执行渗透测试
    result = leader.run(user_command)

    # 输出结果
    print("\n" + "="*60)
    print("渗透测试完成")
    print("="*60)

    if result.get("status") == "completed":
        report = result.get("report", {})
        print(f"\n摘要: {report.get('summary', '无')}")
        print(f"\n结论: {report.get('conclusion', '无')}")

        findings = report.get("findings", {})
        if findings:
            print("\n发现:")
            for level, items in findings.items():
                if items:
                    print(f"  [{level}]: {len(items) if isinstance(items, list) else items}")

        recommendations = report.get("recommendations", [])
        if recommendations:
            print("\n建议:")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")
    elif result.get("status") == "aborted":
        print(f"\n测试被中止: {result.get('reason', '未知原因')}")
    else:
        print(f"\n测试状态: {result.get('status', '未知')}")

    return result


def interactive_mode():
    """交互模式"""
    print("="*60)
    print("Hunter 自动化渗透测试系统 - 交互模式")
    print("输入 'exit' 或 'quit' 退出")
    print("="*60)

    while True:
        print("\n请输入渗透测试需求:")
        user_command = input("> ").strip()

        if user_command.lower() in ['exit', 'quit', 'q']:
            print("再见!")
            break

        if not user_command:
            print("请输入有效的命令")
            continue

        write_to_logs(f"user: {user_command}")

        try:
            main(user_command)
        except KeyboardInterrupt:
            print("\n\n用户中断")
        except Exception as e:
            print(f"\n执行出错: {e}")
            write_to_logs(f"error: {e}")


if __name__ == '__main__':
    # 更改工作目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    import sys
    if len(sys.argv) > 1:
        # 命令行参数模式
        user_command = " ".join(sys.argv[1:])
        write_to_logs(f"user: {user_command}")
        main(user_command)
    else:
        # 交互模式
        interactive_mode()
