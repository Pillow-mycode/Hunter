import os
import subprocess
import threading
import time
import errno

import pyte

from dotenv import load_dotenv
load_dotenv(override=True)


from agent.pojo.hawkeye_config import HawkeyeConfig
from agent.smart_brain.hawkeye import Hawkeye
from agent.system.pty_monitor import PTYOutputMonitor

my_platform = "linux"

hawkeye = Hawkeye(HawkeyeConfig())

# =========================
# 监控线程（替换旧 TimeCountThread）
# =========================
class MonitorThread(threading.Thread):
    """PTY 输出监控线程，每秒检查停滞，每 10 秒检查时长异常。"""

    def __init__(self, monitor: PTYOutputMonitor, controller=None, result_getter=None):
        super().__init__()
        self.monitor = monitor
        self.controller = controller
        self.result_getter = result_getter
        self.flag = False
        self.is_timeout = False
        self._check_count = 0
        self._max_idle_checks = 120  # 最多等 120 次 idle 检查（~2 分钟停滞）

    def run(self):
        self.flag = True
        consecutive_idle = 0
        while self.flag:
            time.sleep(1)
            self._check_count += 1

            # 每 10 秒检查时长异常
            if self._check_count % 10 == 0:
                anomaly = self.monitor.check_duration_anomaly()
                if anomaly:
                    level = anomaly.get('level', 'warning')
                    print(f"[鹰眼 Layer4] 命令时长异常 ({level}): "
                          f"'{anomaly['command']}' 已运行 {anomaly['elapsed_seconds']:.0f}s, "
                          f"预期 ≤{anomaly['expected_max']}s")
                    if level == 'critical':
                        self.is_timeout = True
                        self.flag = False
                        break

            # Layer 2/3: 停滞检测
            idle_result = self.monitor.check_idle()
            if idle_result.detected:
                if idle_result.method == 'heuristic':
                    consecutive_idle += 1
                    if consecutive_idle >= 3:  # 连续 3 秒判定为交互
                        print(f"[鹰眼 Layer2] 启发式检测到交互提示: {idle_result.matched_text}")
                        _set_interaction()
                        self.flag = False
                        break
                elif idle_result.method == 'llm_needed':
                    consecutive_idle += 1
                    if consecutive_idle >= 5:
                        result = self.result_getter() if self.result_getter else ""
                        needs = check_history(result)
                        if needs:
                            self.flag = False
                            break
                        consecutive_idle = 0
                else:
                    consecutive_idle = 0
            else:
                consecutive_idle = 0

            if consecutive_idle > self._max_idle_checks:
                print("[鹰眼] 输出停滞过久，标记超时")
                self.is_timeout = True
                self.flag = False

    def stop(self):
        self.flag = False

    def reset(self):
        self.monitor.last_output_time = time.time()
        self._check_count = 0


def _set_interaction():
    global active_process
    active_process["needs_interaction"] = True


# =========================
# 平台适配
# =========================
def adapt_platform(platform: str, bash: str):
    """
    Linux: PTY
    Windows: winpty
    """
    try:
        if platform == "linux":
            import pty

            master_fd, slave_fd = pty.openpty()

            # ❗ PTY 模式不要用 text=True
            process = subprocess.Popen(
                bash,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                shell=True
            )

            os.close(slave_fd)
            return process, master_fd, None, "pty"

        elif platform == "windows":
            import winpty

            pty_process = winpty.PTY(80, 24)
            pty_process.spawn(f"cmd.exe /c {bash}")
            return pty_process, None, None, "winpty"

        else:
            return None, None, None, None

    except Exception as e:
        raise e


# =========================
# 全局活跃进程状态
# =========================
active_process = {
    "process": None,
    "master_fd": None,
    "output_history": "",
    "bash": "",
    "caller": None,
    "timer": None,
    "needs_interaction": False,
    "type": None
}

output_lock = threading.Lock()


def _clean_terminal_output(text: str) -> str:
    """
    使用 pyte 虚拟终端模拟器清理 PTY 原始输出。
    像真实终端一样处理 ANSI 转义序列、\\r 回车覆盖、光标控制等，
    返回终端屏幕上实际可见的内容。通用方案，不依赖特定工具的输出格式。
    """
    if not text:
        return text

    screen = pyte.HistoryScreen(250, 50, history=100000)
    stream = pyte.Stream(screen)
    stream.feed(text)

    # 提取历史（滚出屏幕的行）+ 当前屏幕内容
    lines = []
    for h in screen.history.top:
        chars = ''.join(c.data for c in h.values()).rstrip()
        lines.append(chars)
    for l in screen.display:
        lines.append(l.rstrip())

    # 去掉尾部空行，保留中间空行
    while lines and not lines[-1]:
        lines.pop()

    return '\n'.join(lines)


# =========================
# 鹰眼判断
# =========================
def check_history(result: str) -> bool:
    """
    检查是否需要用户交互

    Returns:
        True 如果需要交互，False 否则
    """
    global active_process

    if active_process["needs_interaction"]:
        print("[鹰眼] 已标记需要交互，跳过检查")
        return True

    # 清理 ANSI 转义序列，避免干扰 LLM 判断
    result = _clean_terminal_output(result)

    max_len = 1000
    truncated = False
    if len(result) > max_len:
        result = result[:500] + "\n(中间省略...)\n" + result[-500:]
        truncated = True

    print(f"[鹰眼] 开始检查，输出长度: {len(result)}字符{' (已截断)' if truncated else ''}")
    print(f"[鹰眼] 输出末尾: {repr(result[-200:]) if result else '(空)'}")

    check_result = hawkeye.check(result)
    print(f"[鹰眼] 判断结果: {'需要交互' if check_result else '无需交互'}")

    if check_result:
        print("[鹰眼] 需要输入")
        active_process["needs_interaction"] = True
        return True

    return False


# =========================
# 主执行函数
# =========================
def sys_shell(bash: str):
    global active_process

    print(f"正在运行的命令: {bash}")
    output = ""

    try:
        process, master_fd, _, pty_type = adapt_platform(my_platform, bash)
    except Exception as e:
        return str(e)

    monitor = PTYOutputMonitor()
    monitor.start_command(bash)
    timer = MonitorThread(
        monitor=monitor,
        controller=process,
        result_getter=lambda: _safe_get_output(output),
    )
    timer.start()

    try:
        active_process["needs_interaction"] = False

        if pty_type == "pty":
            import select

            while True:
                # 检查是否需要交互
                if active_process["needs_interaction"]:
                    _save_active(process, master_fd, output, bash, timer, "pty")
                    return _clean_terminal_output(output)

                # 检查是否超时，超时后触发回调（保存进程状态，让武器大师处理）
                if timer.is_timeout:
                    print("[超时] 命令执行超时，触发回调")
                    active_process["needs_interaction"] = True
                    _save_active(process, master_fd, output, bash, timer, "pty")
                    return _clean_terminal_output(output)

                try:
                    readable, _, _ = select.select([master_fd], [], [], 0.1)
                    if readable:
                        try:
                            data = os.read(master_fd, 1024)
                        except OSError as e:
                            if e.errno == errno.EIO:
                                break
                            raise

                        if not data:
                            break

                        decoded = data.decode('utf-8', errors='replace')
                        with output_lock:
                            output += decoded
                        # 实时打印到控制台
                        print(decoded, end='', flush=True)
                        write_to_logs(decoded)
                        timer.reset()

                        # Layer 1: 模式匹配（每次新输出触发）
                        l1_result = monitor.feed_output(decoded)
                        if l1_result.detected:
                            print(f"[鹰眼 Layer1] 检测到交互提示: {l1_result.matched_text}")
                            _set_interaction()
                            _save_active(process, master_fd, output, bash, timer, "pty")
                            return _clean_terminal_output(output)
                        # 读到数据继续循环，不检查 poll()

                    elif process.poll() is not None:
                        # 无数据可读且进程已退出 → 确定完成
                        break

                except Exception:
                    break

        elif pty_type == "winpty":
            while process.isalive():
                # 检查是否需要交互
                if active_process["needs_interaction"]:
                    _save_active(process, None, output, bash, timer, "winpty")
                    return _clean_terminal_output(output)

                # 检查是否超时，超时后触发回调
                if timer.is_timeout:
                    print("[超时] 命令执行超时，触发回调")
                    active_process["needs_interaction"] = True
                    _save_active(process, None, output, bash, timer, "winpty")
                    return _clean_terminal_output(output)

                data = process.read()
                if data:
                    with output_lock:
                        output += data
                    # 实时打印到控制台
                    print(data, end='', flush=True)
                    write_to_logs(data)
                    timer.reset()

                    # Layer 1: 模式匹配
                    l1_result = monitor.feed_output(data)
                    if l1_result.detected:
                        print(f"[鹰眼 Layer1] 检测到交互提示: {l1_result.matched_text}")
                        _set_interaction()
                        _save_active(process, None, output, bash, timer, "winpty")
                        return _clean_terminal_output(output)

        return _clean_terminal_output(output)

    finally:
        timer.stop()
        if pty_type == "pty" and master_fd:
            try:
                os.close(master_fd)
            except OSError:
                pass


# =========================
# 写入交互输入
# =========================
def write_input_to_active_process(input_text: str):
    global active_process

    if active_process["process"] is None:
        write_to_logs("警告: 没有活跃进程")
        return None

    process = active_process["process"]
    master_fd = active_process["master_fd"]
    output = ""
    pty_type = active_process["type"]
    bash = active_process["bash"]

    monitor = PTYOutputMonitor()
    monitor.start_command(bash)
    timer = MonitorThread(
        monitor=monitor,
        controller=process,
        result_getter=lambda: _safe_get_output(output),
    )
    timer.start()

    try:
        # ===== 写输入 =====
        try:
            if pty_type == "pty":
                os.write(master_fd, (input_text + "\n").encode())
            elif pty_type == "winpty":
                process.write(input_text + "\r\n")
        except Exception as e:
            write_to_logs(f"写入输入失败: {e}")
            return None

        active_process["needs_interaction"] = False

        # ===== 继续读取 =====
        if pty_type == "pty":
            import select

            while True:
                if active_process["needs_interaction"]:
                    active_process["output_history"] = output
                    return _clean_terminal_output(output)

                try:
                    readable, _, _ = select.select([master_fd], [], [], 0.1)
                    if readable:
                        try:
                            data = os.read(master_fd, 1024)
                        except OSError as e:
                            if e.errno == errno.EIO:
                                break
                            raise

                        if not data:
                            break

                        decoded = data.decode(errors="ignore")
                        with output_lock:
                            output += decoded
                        # 实时打印到控制台
                        print(decoded, end='', flush=True)
                        write_to_logs(decoded)
                        timer.reset()

                        # Layer 1: 模式匹配
                        l1_result = monitor.feed_output(decoded)
                        if l1_result.detected:
                            print(f"[鹰眼 Layer1] 检测到交互提示: {l1_result.matched_text}")
                            _set_interaction()
                            active_process["output_history"] = output
                            return _clean_terminal_output(output)

                    elif process.poll() is not None:
                        break

                except Exception:
                    break

        elif pty_type == "winpty":
            while process.isalive():
                if active_process["needs_interaction"]:
                    active_process["output_history"] = output
                    return _clean_terminal_output(output)

                data = process.read()
                if data:
                    with output_lock:
                        output += data
                    # 实时打印到控制台
                    print(data, end='', flush=True)
                    write_to_logs(data)
                    timer.reset()

                    # Layer 1: 模式匹配
                    l1_result = monitor.feed_output(data)
                    if l1_result.detected:
                        print(f"[鹰眼 Layer1] 检测到交互提示: {l1_result.matched_text}")
                        _set_interaction()
                        active_process["output_history"] = output
                        return _clean_terminal_output(output)

        clear_active_process()
        return _clean_terminal_output(output)

    finally:
        timer.stop()


# =========================
# 工具函数
# =========================
def _save_active(process, master_fd, output, bash, timer, pty_type):
    active_process["process"] = process
    active_process["master_fd"] = master_fd
    active_process["output_history"] = output
    active_process["bash"] = bash
    active_process["timer"] = timer
    active_process["type"] = pty_type


def clear_active_process():
    active_process.update({
        "process": None,
        "master_fd": None,
        "output_history": "",
        "bash": "",
        "timer": None,
        "needs_interaction": False,
        "type": None
    })


def _safe_get_output(output_ref):
    with output_lock:
        return output_ref


import re

_SENSITIVE_PATTERNS = [
    # Command-line password arguments
    (re.compile(r'(-p|--password|--pass|--pwd)\s+\S+', re.I), r'\1 [FILTERED]'),
    (re.compile(r'(password|passwd|pwd)\s*=\s*\S+', re.I), r'\1=[FILTERED]'),
    # API keys in commands (e.g. --api-key sk-xxx)
    (re.compile(r'(--api-key|--apikey|--api_key)\s+\S+', re.I), r'\1 [FILTERED]'),
    # SSH passwords
    (re.compile(r'sshpass\s+-p\s+\S+', re.I), 'sshpass -p [FILTERED]'),
]


def _sanitize_for_log(text: str) -> str:
    """掩码日志中的敏感信息（密码、API Key 等）。"""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def write_to_logs(content):
    path = "../logs/command_log_progress.txt"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    content = _sanitize_for_log(str(content))

    with open(path, 'a', encoding='utf-8') as f:
        import datetime
        ts = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        f.write(f"{ts} - {content}\n")


# =========================
# 测试入口
# =========================
if __name__ == '__main__':
    print(sys_shell("nmap --help"))
