import os
import subprocess
import threading
import time

from agent.pojo.hawkeye_config import HawkeyeConfig
from agent.smart_brain.hawkeye import Hawkeye

my_platform = "windows"


# 时间线程，到一定时间检测一次。防止命令行需要交互导致堵塞
class TimeCountThread(threading.Thread):
    def __init__(self, duration, controller=None, result_getter=None, caller=None):
        """
        :param result_getter: 函数，用于动态获取最新的输出结果
        """
        super().__init__()
        self.controller = controller
        self.duration = duration
        self.count = 0
        self.flag = False
        self.result_getter = result_getter
        self.caller = caller

    def run(self):
        self.flag = True
        while self.flag:
            time.sleep(1)
            self.count += 1
            if self.count >= self.duration:
                self.count = 0
                result = self.result_getter() if self.result_getter else ""
                print(f"result: {result}")
                check_history(result, self.caller, self.controller)

    def stop(self):
        self.flag = False
        self.count = 0

    def reset(self):
        self.count = 0


def adapt_platform(platform: str, bash: str):
    try:
        if platform == "windows":
            return subprocess.Popen(
                ["cmd", "/c", bash],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="gbk",
                errors="replace",
                bufsize=0,
                shell=False,
            )

        elif platform == "linux":
            return subprocess.Popen(
                ["/bin/sh", "-c", bash],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=0,
                shell=False,
            )
        else:
            return None
    except:
        raise


hawkeye = Hawkeye(HawkeyeConfig())


# 全局变量，保存活跃的进程状态
active_process = {
    "process": None,           # 进程对象
    "output_history": "",      # 已读取的输出
    "bash": "",                # 原始命令
    "caller": None,            # 调用者
    "timer": None,             # 计时器
    "needs_interaction": False # 是否需要交互
}


# 用鹰眼查看对话历史，返回是否需要用户交互
def check_history(result: str, caller, process):
    global active_process

    # 如果已经标记需要交互，就不再重复检查
    if active_process["needs_interaction"]:
        return

    max_len = 1000
    head_len = 500
    tail_len = 500

    if len(result) > max_len:
        result = result[:head_len] + "\n(中间部分已省略...)\n" + result[-tail_len:]

    is_interaction = hawkeye.check(result)
    print(result)
    print(is_interaction)

    if is_interaction:
        # 只标记需要交互，不处理输入，让主线程来处理
        active_process["needs_interaction"] = True

        # 主动写入一个换行符，解除主线程readline的阻塞
        if process and process.stdin:
            try:
                process.stdin.write("\n")
                process.stdin.flush()
            except Exception as e:
                print(f"写入换行符时出错: {e}")


def sys_shell(bash: str, caller=None):
    global active_process

    # 情况1：有活跃进程，说明是继续执行
    if active_process["process"] is not None:
        print(f"继续执行命令: {active_process['bash']}")

        # 恢复进程状态
        process = active_process["process"]
        output = active_process["output_history"]
        timer = active_process["timer"]

        # 1. 调用大模型获取输入
        result = active_process["output_history"]
        res = ""
        if active_process["caller"] and active_process["caller"].master_reminder:
            print(f"\n检测到需要交互，正在调用大模型获取输入...")
            try:
                res = active_process["caller"].master_reminder(result)
                print(f"大模型返回的输入: {res}")
            except Exception as e:
                print(f"调用大模型时出错: {e}")
                res = ""

        # 2. 写入输入到进程
        if res and process and process.stdin:
            try:
                process.stdin.write(res + "\n")
                process.stdin.flush()
                print("输入已写入进程\n")
            except Exception as e:
                print(f"写入输入时出错: {e}")

        # 3. 继续读取输出
        active_process["needs_interaction"] = False

        for line in iter(process.stdout.readline, ''):
            # 检查是否再次需要交互
            if active_process["needs_interaction"]:
                print("\n检测到再次需要交互，保存进程状态并退出")
                # 保存当前状态
                active_process["output_history"] = output
                # 保持进程和timer运行
                print(f"已保存进程状态，当前输出长度: {len(output)} 字符")
                return output

            timer.reset()
            if line.strip():
                print(line, end="")
            output += line

        # 4. 检查进程是否结束
        if process.poll() is not None:
            print("\n进程已结束")
            timer.stop()
            # 清理活跃进程状态
            active_process["process"] = None
            active_process["output_history"] = ""
            active_process["bash"] = ""
            active_process["caller"] = None
            active_process["timer"] = None
            active_process["needs_interaction"] = False

        return output

    # 情况2：新命令
    print(f"正在运行的命令: {bash}")
    output = ""

    try:
        process = adapt_platform(my_platform, bash)
    except Exception as e:
        return str(e)

    # 传 lambda 动态获取 output
    timer = TimeCountThread(
        duration=10,
        controller=process,
        result_getter=lambda: output,
        caller=caller
    )
    timer.start()

    # 重置交互标志
    active_process["needs_interaction"] = False

    for line in iter(process.stdout.readline, ''):
        # 检查是否需要交互
        if active_process["needs_interaction"]:
            print("\n检测到需要交互，保存进程状态并退出")
            # 保存进程状态
            active_process["process"] = process
            active_process["output_history"] = output
            active_process["bash"] = bash
            active_process["caller"] = caller
            active_process["timer"] = timer
            # 保持进程和timer运行
            print(f"已保存进程状态，当前输出长度: {len(output)} 字符")
            return output

        timer.reset()
        if line.strip():
            print(line, end="")
        output += line
        print(f"output: {output}")

    # 正常结束
    timer.stop()
    print(f"命令执行完成，输出长度: {len(output)} 字符")
    return output


def write_to_logs(content):
    path = "../logs/command_log_progress.txt"
    dir_path = os.path.dirname(path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path)

    with open(path, 'a', encoding='utf-8') as f:
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        f.write(f"{timestamp} - {content}\n")

