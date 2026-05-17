"""PTYOutputMonitor — 事件驱动的四层终端交互检测器"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

# ─── DetectionResult ─────────────────────────────────────────────

@dataclass
class DetectionResult:
    detected: bool = False
    method: str = ""          # pattern / heuristic / idle_check / llm_needed / duration
    prompt_type: str = ""     # sudo_password / yes_no / confirm / generic_prompt / unknown
    confidence: float = 0.0
    matched_text: str = ""
    snippet: str = ""


# ─── Layer 1: 预编译交互提示正则 ─────────────────────────────────

INTERACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\[sudo\]\s+password\s+for\s+\w+\s*:?\s*$', re.I), 'sudo_password'),
    (re.compile(r'Password:\s*$'), 'password'),
    (re.compile(r'Enter\s+password\s*:?\s*$', re.I), 'password'),
    (re.compile(r'\[y/[Nn]\]\s*$'), 'yes_no'),
    (re.compile(r'\[Y/n\]\s*$'), 'yes_no'),
    (re.compile(r'\(yes/no\)\s*$', re.I), 'yes_no'),
    (re.compile(r'Continue\?\s*\[?\s*(y|yes|n|no)\s*\]?\s*$', re.I), 'confirm'),
    (re.compile(r'Are\s+you\s+sure\?\s*$', re.I), 'confirm'),
    (re.compile(r'Press\s+(any\s+key|Enter|return)\s*', re.I), 'press_key'),
    (re.compile(r'请输入.*[:：]?\s*$'), 'input_zh'),
    (re.compile(r'确认.*[:：]?\s*$'), 'confirm_zh'),
    (re.compile(r'\[确认\]\s*$'), 'confirm_zh'),
    (re.compile(r'\[\?\]\s*'), 'prompt'),
]

# ─── Layer 4: 命令时长估算 ───────────────────────────────────────

KNOWN_DURATIONS: list[tuple[list[str], int, int, str]] = [
    (['whoami', 'id', 'pwd', 'ls', 'cat', 'echo', 'date', 'uname',
      'hostname', 'which', 'whereis'], 0, 3, '瞬时命令'),
    (['nmap -sn', 'nmap -sL'], 5, 120, 'nmap 主机发现'),
    (['nmap -sV', 'nmap -sC', 'nmap -A'], 30, 600, 'nmap 服务扫描'),
    (['nmap -p-'], 60, 3600, 'nmap 全端口扫描'),
    (['nmap'], 10, 300, 'nmap 默认扫描'),
    (['ffuf'], 30, 1800, '目录扫描'),
    (['sqlmap'], 60, 3600, 'SQL 注入测试'),
    (['hydra', 'medusa'], 120, 7200, '密码爆破'),
    (['hashcat', 'john'], 30, 3600, '密码破解'),
    (['nikto'], 60, 1800, 'Web 漏洞扫描'),
    (['curl', 'wget'], 5, 300, '网络请求'),
    (['ping'], 10, 60, 'Ping'),
    (['traceroute'], 10, 120, '路由追踪'),
    (['dig', 'nslookup', 'host'], 2, 30, 'DNS 查询'),
    (['python', 'python3', 'ruby', 'perl'], 5, 300, '脚本执行'),
    (['apt', 'apt-get', 'yum', 'pip', 'gem', 'npm', 'go install'], 30, 600, '包安装'),
]


# ─── PTYOutputMonitor ────────────────────────────────────────────

class PTYOutputMonitor:
    """事件驱动的 PTY 输出监控器，四层检测体系。"""

    def __init__(self, stall_threshold: float = 2.0):
        self.output_buffer: str = ""
        self.last_output_time: float = time.time()
        self.command_start_time: Optional[float] = None
        self.current_command: str = ""
        self.stall_threshold = stall_threshold
        self.comm_bus = None

    # ── Layer 1: 模式匹配（每次新输出触发） ────────────────────

    def feed_output(self, new_chars: str) -> DetectionResult:
        self.output_buffer = (self.output_buffer + new_chars)[-2000:]
        self.last_output_time = time.time()

        tail = self.output_buffer[-500:]
        for pattern, prompt_type in INTERACTION_PATTERNS:
            match = pattern.search(tail)
            if match:
                return DetectionResult(
                    detected=True, method='pattern',
                    prompt_type=prompt_type, confidence=0.98,
                    matched_text=match.group(),
                )
        return DetectionResult(detected=False)

    # ── Layer 2 + 3: 停滞检测 ─────────────────────────────────

    def check_idle(self) -> DetectionResult:
        idle_sec = time.time() - self.last_output_time
        if idle_sec < self.stall_threshold:
            return DetectionResult(detected=False, method='idle_check')

        tail = self.output_buffer[-500:]
        last_line = tail.split('\n')[-1].strip()

        # Layer 2: 启发式判断
        if self._looks_like_prompt(last_line):
            return DetectionResult(
                detected=True, method='heuristic',
                prompt_type='generic_prompt', confidence=0.75,
                matched_text=last_line[:100],
            )

        # Layer 3 trigger: 停滞超 2 倍阈值 → 建议 LLM 介入
        if idle_sec >= self.stall_threshold * 2:
            return DetectionResult(
                detected=True, method='llm_needed',
                prompt_type='unknown', confidence=0.0,
                snippet=tail[-300:],
            )

        return DetectionResult(detected=False, method='idle_check')

    def _looks_like_prompt(self, line: str) -> bool:
        if not line:
            return False
        if line[-1] in (':', '?', '>', '》'):
            return True
        if any(line.endswith(w) for w in ['输入', '确认', '继续', '密码', '口令']):
            return True
        return False

    # ── Layer 4: 命令时长异常检测 ──────────────────────────────

    def start_command(self, command: str):
        self.command_start_time = time.time()
        self.current_command = command

    def check_duration_anomaly(self) -> Optional[dict]:
        if not self.command_start_time:
            return None
        elapsed = time.time() - self.command_start_time
        expected = self._estimate_duration(self.current_command)
        if expected and elapsed > expected['max_seconds']:
            return {
                'command': self.current_command,
                'elapsed_seconds': elapsed,
                'expected_max': expected['max_seconds'],
                'level': 'critical' if elapsed > expected['max_seconds'] * 2 else 'warning',
            }
        return None

    def _estimate_duration(self, command: str) -> Optional[dict]:
        cmd_lower = command.strip().lower()
        for keywords, min_s, max_s, reason in KNOWN_DURATIONS:
            for kw in keywords:
                if kw in cmd_lower:
                    return {'min_seconds': min_s, 'max_seconds': max_s, 'reason': reason}

        if any(kw in cmd_lower for kw in ['http', 'https', '://', 'scan', 'brute', 'enum', 'fuzz']):
            return {'min_seconds': 10, 'max_seconds': 600, 'reason': '网络相关命令'}
        if len(command) > 100:
            return {'min_seconds': 5, 'max_seconds': 300, 'reason': '长命令'}
        return None
