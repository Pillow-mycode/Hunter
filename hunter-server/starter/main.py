"""Hunter CLI — 使用 AgentLoop 模式执行渗透测试"""
import os
import sys
import threading
from dotenv import load_dotenv
load_dotenv(override=True)

from agent.pojo.leader_config import AttackLeaderConfig
from agent.smart_brain.attack_leader import AttackLeader
from agent.team.comm_bus import CommunicationBus
from agent.team.blackboard import Blackboard
from agent.team.agent_loop import AgentLoop
from agent.system.system_command import write_to_logs


def main(user_command: str):
    """CLI 入口：创建 Leader + CommBus + Blackboard + AgentLoop，等待任务完成"""
    print("=" * 60)
    print("Hunter 自动化渗透测试系统")
    print("=" * 60)

    comm_bus = CommunicationBus()
    blackboard = Blackboard()

    comm_bus.register_agent("leader")
    blackboard.register_agent("leader")

    config = AttackLeaderConfig()
    leader = AttackLeader(config, comm_bus=comm_bus, blackboard=blackboard)

    # 写入任务目标
    blackboard.write("mission", "objective", user_command)
    blackboard.write("mission", "status", "in_progress")
    blackboard.add_activity(f"收到任务: {user_command}")

    # 创建并启动 AgentLoop
    agent_loop = AgentLoop(leader, comm_bus, blackboard)
    agent_loop.start()

    print(f"\n[Leader] 开始执行: {user_command}")
    agent_loop.mission_complete.wait()
    result = agent_loop.get_result()

    # 输出结果
    print("\n" + "=" * 60)
    print("渗透测试完成")
    print("=" * 60)

    if result and result.get("type") == "complete":
        print(f"\n结果: {result.get('summary', '无')}")
    else:
        print(f"\n结果: {result}")

    # 输出发现
    findings = blackboard.read("findings")
    if findings:
        print("\n发现:")
        for category, items in findings.items():
            if items:
                if isinstance(items, list):
                    print(f"  [{category}]: {len(items)} 项")
                    for item in items[:5]:
                        print(f"    - {item}")
                    if len(items) > 5:
                        print(f"    ... 等共 {len(items)} 项")
                elif isinstance(items, dict):
                    print(f"  [{category}]: {len(items)} 项")
                    for key, val in list(items.items())[:5]:
                        print(f"    - {key}: {val}")

    return result


def interactive_mode():
    """交互模式"""
    print("=" * 60)
    print("Hunter 自动化渗透测试系统 - 交互模式")
    print("输入 'exit' 或 'quit' 退出")
    print("=" * 60)

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
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if len(sys.argv) > 1:
        user_command = " ".join(sys.argv[1:])
        write_to_logs(f"user: {user_command}")
        main(user_command)
    else:
        interactive_mode()
