# 输出处理模块
# 处理命令输出过长时的保存和截取

import os
import re
from datetime import datetime

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

# ANSI 转义序列正则表达式
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b[PX^_].*?\x1b\\|\x1b\[[\?0-9;]*[hl]')


def clean_ansi_codes(text: str) -> str:
    """
    清理 ANSI 转义序列（颜色代码、光标控制等）

    Args:
        text: 包含 ANSI 转义序列的文本

    Returns:
        清理后的纯文本
    """
    if not text:
        return text

    # 移除 ANSI 转义序列
    cleaned = ANSI_ESCAPE_PATTERN.sub('', text)

    # 移除其他控制字符（保留换行符和制表符）
    cleaned = ''.join(char for char in cleaned if char == '\n' or char == '\t' or (ord(char) >= 32 and ord(char) != 127))

    return cleaned


def extract_tool_name(command: str) -> str:
    """从命令中提取工具名"""
    if not command or not command.strip():
        return "unknown"

    # 获取第一个词
    first_word = command.strip().split()[0]

    # 处理路径
    tool_name = os.path.basename(first_word)

    # 去掉扩展名
    tool_name = re.sub(r'\.(py|sh|bash|exe)$', '', tool_name)

    return tool_name or "unknown"


def save_output_to_file(output: str, command: str, task_id: str = "default") -> str:
    """
    保存输出到文件

    Args:
        output: 命令输出内容
        command: 执行的命令
        task_id: 任务 ID

    Returns:
        保存的文件路径
    """
    # 创建目录
    task_dir = os.path.join(RESULTS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    # 生成文件名
    tool_name = extract_tool_name(command)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{tool_name}_{timestamp}.txt"
    file_path = os.path.join(task_dir, filename)

    # 清理 ANSI 转义序列，避免乱码
    cleaned_output = clean_ansi_codes(output)

    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f"# 命令: {command}\n")
        f.write(f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# 任务ID: {task_id}\n")
        f.write("=" * 60 + "\n\n")
        f.write(cleaned_output)

    return file_path


def process_long_output(output: str, command: str, task_id: str = "default",
                        threshold: int = 30000) -> tuple:
    """
    处理过长的输出（旧接口，供非 ToolMaster 场景使用）

    Args:
        output: 命令输出
        command: 执行的命令
        task_id: 任务 ID
        threshold: 长度阈值

    Returns:
        (处理后的输出, 文件路径或None)
    """
    # 先清理 ANSI 转义序列
    cleaned_output = clean_ansi_codes(output)

    if len(cleaned_output) <= threshold:
        return cleaned_output, None

    # 保存完整输出 + 返回头尾摘要
    file_path = save_output_to_file(output, command, task_id)

    head_len = 5000
    tail_len = 10000
    head = cleaned_output[:head_len]
    tail = cleaned_output[-tail_len:]

    result = (
        f"[系统] 输出过长({len(cleaned_output)}字符)。完整结果已保存至: {file_path}\n"
        f"前{head_len}字符: {head}\n"
        f"...(省略中间部分)...\n"
        f"末尾{tail_len}字符: {tail}\n"
    )

    return result, file_path


# ── 控制台紧凑输出（git diff --stat 风格）────────────────────────

def format_console_output(command: str, output: str, max_lines: int = 6) -> str:
    """将命令输出格式化为紧凑的控制台显示。

    Bash(nmap -sV target)
      ⎿   Starting Nmap 7.94 ...
          PORT     STATE    SERVICE     VERSION
          22/tcp   open     ssh         OpenSSH 8.2p1
         … +45 lines / 3247 chars
    """
    if not output:
        return f"Bash({command})\n  ⎿   (无输出)"

    lines = output.split('\n')
    total_lines = len(lines)
    total_chars = len(output)

    display_lines = lines[:max_lines]

    result = f"Bash({command})\n"
    for i, line in enumerate(display_lines):
        prefix = "  ⎿   " if i == 0 else "      "
        if len(line) > 120:
            line = line[:117] + "..."
        result += f"{prefix}{line}\n"

    remaining = total_lines - max_lines
    if remaining > 0:
        result += f"     … +{remaining} 行 / {total_chars} 字符"

    return result


# ToolMaster 输出分级阈值
TOOLMASTER_FULL_LIMIT = 20_000   # ≤20K 全量给 LLM，以上头+中+尾拼接


def process_toolmaster_output(output: str, command: str, task_id: str = "default") -> tuple:
    """
    ToolMaster 命令输出分级处理：

    - ≤ 20K 字符：全量返回，ToolMaster LLM 直接消费
    - > 20K：头 20K + 中间 10K + 尾 20K 拼接，提示疑似假阳性需增强过滤

    Args:
        output: 原始命令输出
        command: 执行的命令
        task_id: 任务 ID

    Returns:
        (处理后的文本, 文件路径或None)
    """
    cleaned = clean_ansi_codes(output)
    file_path = save_output_to_file(output, command, task_id)

    length = len(cleaned)

    if length <= TOOLMASTER_FULL_LIMIT:
        return cleaned, file_path

    # > 20K：头+中+尾拼接，大概率是假阳性（重复输出/无限重定向/工具卡死）
    head = cleaned[:20000]
    mid_start = max(20000, (length - 10000) // 2)
    mid = cleaned[mid_start:mid_start + 10000]
    tail = cleaned[-20000:]

    result = (
        f"[系统警告] 输出 {length} 字符，超过 20K 上限，极可能是假阳性（死循环、重复输出、垃圾数据）。\n"
        f"完整输出已保存: {file_path}\n"
        f"请增强过滤条件缩小输出，或忽略此结果继续任务。\n"
        f"\n--- 头部 {len(head)} 字符 ---\n{head}\n"
        f"\n--- 中部 {len(mid)} 字符 (位置 ~{mid_start}) ---\n{mid}\n"
        f"\n--- 尾部 {len(tail)} 字符 ---\n{tail}"
    )

    return result, file_path
