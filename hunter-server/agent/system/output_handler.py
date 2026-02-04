# 输出处理模块
# 处理命令输出过长时的保存和截取

import os
import re
from datetime import datetime

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")


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

    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f"# 命令: {command}\n")
        f.write(f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# 任务ID: {task_id}\n")
        f.write("=" * 60 + "\n\n")
        f.write(output)

    return file_path


def extract_important_lines(text: str, max_len: int) -> str:
    """
    从文本中提取关键行

    Args:
        text: 原始文本
        max_len: 最大长度

    Returns:
        提取的关键行
    """
    # 关键词列表
    keywords = [
        # HTTP 状态码
        '[200]', '[201]', '[301]', '[302]', '[303]', '[307]', '[308]',
        '[401]', '[403]', '[500]', '[502]', '[503]',
        '200 ok', '301 moved', '302 found', '403 forbidden',

        # 发现类
        'found', 'discovered', 'detected', 'identified',
        'vulnerable', 'vulnerability', 'injection', 'exploit',

        # 端口和服务
        'open', 'filtered', 'closed',
        '/tcp', '/udp',

        # 敏感目录和文件
        'admin', 'login', 'password', 'passwd', 'config',
        'backup', 'database', 'db', 'sql', 'dump',
        '.zip', '.tar', '.gz', '.bak', '.old', '.sql',
        'phpinfo', 'phpmyadmin', 'wp-admin', 'wp-config',
        '.git', '.svn', '.env', 'robots.txt', 'sitemap',

        # 认证相关
        'credential', 'token', 'session', 'cookie', 'auth',

        # 错误和警告
        'error', 'warning', 'critical', 'success', 'fail',

        # 注入相关
        'payload', 'parameter', 'injectable', 'sqli', 'xss',
    ]

    important = []
    seen = set()  # 去重

    for line in text.split('\n'):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        line_lower = line_stripped.lower()

        # 检查是否包含关键词
        if any(kw in line_lower for kw in keywords):
            # 去重
            if line_stripped not in seen:
                seen.add(line_stripped)
                important.append(line_stripped)

    result = '\n'.join(important)

    # 如果超过最大长度，截断
    if len(result) > max_len:
        result = result[:max_len] + "\n[... 更多关键行已省略 ...]"

    return result


def smart_truncate(output: str, max_len: int = 30000, file_path: str = None) -> str:
    """
    智能截取输出

    Args:
        output: 原始输出
        max_len: 最大长度
        file_path: 完整结果文件路径（可选）

    Returns:
        截取后的输出
    """
    if len(output) <= max_len:
        return output

    # 分配比例
    head_ratio = 0.2   # 开头 20%
    tail_ratio = 0.35  # 结尾 35%
    middle_ratio = 0.45  # 中间关键行 45%

    head_len = int(max_len * head_ratio)
    tail_len = int(max_len * tail_ratio)
    middle_len = int(max_len * middle_ratio)

    # 提取各部分
    head = output[:head_len]
    tail = output[-tail_len:]

    # 中间部分提取关键行
    middle_start = head_len
    middle_end = len(output) - tail_len
    if middle_end > middle_start:
        middle_raw = output[middle_start:middle_end]
        middle = extract_important_lines(middle_raw, middle_len)
    else:
        middle = ""

    # 构建截断提示
    file_hint = ""
    if file_path:
        file_hint = f"完整结果已保存到: {file_path}\n"

    # 组装结果
    separator = "\n" + "=" * 40 + "\n"

    result = (
        f"[输出过长({len(output)}字符)，以下是摘要]\n"
        f"{file_hint}"
        f"{separator}"
        f"[开头部分]\n{head}"
        f"{separator}"
        f"[中间关键行]\n{middle if middle else '(无匹配的关键行)'}"
        f"{separator}"
        f"[结尾部分]\n{tail}"
    )

    return result


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
    if len(output) <= threshold:
        return output, None

    # 保存完整输出到文件
    file_path = save_output_to_file(output, command, task_id)

    # 智能截取
    truncated = smart_truncate(output, threshold, file_path)

    return truncated, file_path
