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
    处理过长的输出

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

    # 使用数据分析员处理超长输出
    try:
        from agent.smart_brain.data_analyst import analyze_long_output
        return analyze_long_output(output, command, task_id)
    except Exception as e:
        print(f"[输出处理] 数据分析员调用失败: {e}，使用备用方案")
        # 备用方案：保存文件 + 简单截取
        file_path = save_output_to_file(output, command, task_id)

        head_len = 5000
        tail_len = 10000
        head = cleaned_output[:head_len]
        tail = cleaned_output[-tail_len:]

        result = (
            f"[输出过长({len(cleaned_output)}字符)]\n"
            f"完整结果已保存到: {file_path}\n"
            f"\n【输出开头】\n{head}\n"
            f"\n...(省略中间部分)...\n"
            f"\n【输出结尾】\n{tail}"
        )

        return result, file_path
