"""
多参数暴力破解工具 v4.2 - 生产者消费者队列版
修复版本：解决卡住问题，优化线程退出机制
"""

import argparse
import sys
import os
import time
import json
import threading
import queue
import traceback
from typing import List, Dict, Tuple, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from colorama import init, Fore, Style
import re
from itertools import product, islice
from dataclasses import dataclass, field
import signal

# 初始化颜色
init(autoreset=True)


class ParameterSource:
    """参数值来源"""

    def __init__(self, spec: str):
        """
        初始化参数源

        Args:
            spec: 参数规格，可以是：
                1. 文件路径: "users.txt"
                2. 固定值: "admin"
                3. 多个值: "val1,val2,val3"
        """
        self.spec = spec.strip()
        self._values = None

    def get_values(self) -> List[str]:
        """获取参数值列表"""
        if self._values is not None:
            return self._values

        # 如果是文件路径
        if os.path.exists(self.spec):
            with open(self.spec, 'r', encoding='utf-8', errors='ignore') as f:
                self._values = [line.strip() for line in f if line.strip()]
        # 如果是逗号分隔的多个值
        elif ',' in self.spec:
            self._values = [v.strip() for v in self.spec.split(',') if v.strip()]
        # 单个固定值
        else:
            self._values = [self.spec]

        return self._values

    def get_count(self) -> int:
        """获取值的数量"""
        return len(self.get_values())


@dataclass
class ParamConfig:
    """参数配置"""
    name: str
    source: ParameterSource
    is_required: bool = True

    def get_values(self) -> List[str]:
        """获取参数值"""
        return self.source.get_values()

    def get_count(self) -> int:
        """获取值的数量"""
        return len(self.get_values())


@dataclass
class AttackConfig:
    """攻击配置"""
    url: str
    method: str = "POST"
    params: Dict[str, ParamConfig] = field(default_factory=dict)
    threads: int = 5
    timeout: int = 10
    retry: int = 3
    delay: float = 0
    proxy: Optional[str] = None
    cookies: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    success_criteria: Dict[str, Any] = field(default_factory=dict)
    output_dir: str = "results"
    verbose: bool = False
    quiet: bool = False
    save_all: bool = False
    save_results: bool = True   # 是否保存结果文件
    show_success: bool = False  # 是否显示实时成功信息
    max_queue_size: int = 1000
    batch_size: int = 100  # 新增：批量大小，提高效率

    def get_total_combinations(self) -> int:
        """计算总组合数"""
        total = 1
        for param in self.params.values():
            total *= param.get_count()
        return total


class TaskQueue:
    """任务队列管理器"""

    def __init__(self, config: AttackConfig):
        self.config = config
        self.task_queue = queue.Queue(maxsize=config.max_queue_size)
        self.result_queue = queue.Queue(maxsize=config.max_queue_size)
        self.stop_event = threading.Event()
        self.producer_finished = threading.Event()
        self.consumers_finished = threading.Event()
        self.stats_lock = threading.Lock()

        # 统计信息
        self.stats = {
            'tasks_generated': 0,
            'tasks_processed': 0,
            'tasks_success': 0,
            'tasks_failed': 0,
            'requests_sent': 0,
            'start_time': 0,
            'end_time': 0
        }

    def put_task(self, task: Dict[str, str]) -> bool:
        """添加任务到队列，返回是否成功"""
        if self.stop_event.is_set():
            return False

        try:
            self.task_queue.put(task, timeout=0.1, block=True)
            with self.stats_lock:
                self.stats['tasks_generated'] += 1
            return True
        except queue.Full:
            return False
        except Exception as e:
            if self.config.verbose:
                print(f"{Fore.RED}[队列] 添加任务失败: {e}{Style.RESET_ALL}")
            return False

    def get_task(self, timeout: float = 0.5) -> Optional[Dict[str, str]]:
        """从队列获取任务"""
        try:
            task = self.task_queue.get(timeout=timeout)
            return task
        except queue.Empty:
            return None
        except Exception as e:
            if self.config.verbose:
                print(f"{Fore.RED}[队列] 获取任务失败: {e}{Style.RESET_ALL}")
            return None

    def task_done(self):
        """标记任务完成"""
        self.task_queue.task_done()

    def put_result(self, result: Dict[str, Any]) -> bool:
        """添加结果到结果队列"""
        if self.stop_event.is_set():
            return False

        try:
            self.result_queue.put(result, timeout=0.1, block=True)
            return True
        except queue.Full:
            return False
        except Exception as e:
            if self.config.verbose:
                print(f"{Fore.RED}[队列] 添加结果失败: {e}{Style.RESET_ALL}")
            return False

    def get_result(self, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        """从结果队列获取结果"""
        try:
            result = self.result_queue.get(timeout=timeout)
            return result
        except queue.Empty:
            return None
        except Exception as e:
            if self.config.verbose:
                print(f"{Fore.RED}[队列] 获取结果失败: {e}{Style.RESET_ALL}")
            return None

    def result_done(self):
        """标记结果处理完成"""
        self.result_queue.task_done()

    def stop(self):
        """停止队列"""
        self.stop_event.set()

    def is_stopped(self) -> bool:
        """检查是否已停止"""
        return self.stop_event.is_set()

    def get_queue_status(self) -> tuple:
        """获取队列状态"""
        return (
            self.task_queue.qsize(),
            self.result_queue.qsize(),
            self.stop_event.is_set()
        )


class ProducerThread(threading.Thread):
    """生产者线程：生成参数组合"""

    def __init__(self, config: AttackConfig, task_queue: TaskQueue):
        super().__init__(name=f"Producer-{threading.get_ident()}")
        self.config = config
        self.task_queue = task_queue
        self.param_names = list(config.params.keys())
        self.param_values = [config.params[name].get_values() for name in self.param_names]
        self.total_combinations = config.get_total_combinations()
        self.generated_count = 0
        self.daemon = True  # 设置为守护线程

    def run(self):
        """运行生产者"""
        try:
            if self.config.verbose:
                print(f"{Fore.CYAN}[生产者] 开始生成任务，总计: {self.total_combinations:,}{Style.RESET_ALL}")

            # 使用分批生成，避免内存占用过高
            batch = []
            batch_size = self.config.batch_size

            for combination in product(*self.param_values):
                if self.task_queue.is_stopped():
                    break

                params = {}
                for i, value in enumerate(combination):
                    params[self.param_names[i]] = value

                batch.append(params)
                self.generated_count += 1

                # 达到批次大小时批量添加
                if len(batch) >= batch_size:
                    for task in batch:
                        if not self.task_queue.put_task(task):
                            # 队列已满或停止，等待一下
                            time.sleep(0.01)
                    batch.clear()

                # 显示进度
                if self.config.verbose and self.generated_count % 10000 == 0:
                    print(f"{Fore.CYAN}[生产者] 已生成: {self.generated_count:,}/{self.total_combinations:,}{Style.RESET_ALL}")

            # 处理剩余的批次
            for task in batch:
                if self.task_queue.is_stopped():
                    break
                self.task_queue.put_task(task)

            if not self.task_queue.is_stopped():
                if self.config.verbose:
                    print(f"{Fore.CYAN}[生产者] 任务生成完成，共生成 {self.generated_count} 个任务{Style.RESET_ALL}")
            else:
                if self.config.verbose:
                    print(f"{Fore.YELLOW}[生产者] 被中断，已生成 {self.generated_count}/{self.total_combinations} 个任务{Style.RESET_ALL}")

        except KeyboardInterrupt:
            print(f"{Fore.YELLOW}[生产者] 收到键盘中断{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[生产者] 错误: {e}{Style.RESET_ALL}")
            traceback.print_exc()
        finally:
            # 标记生产者已完成
            self.task_queue.producer_finished.set()
            if self.config.verbose:
                print(f"{Fore.CYAN}[生产者] 结束{Style.RESET_ALL}")


class ConsumerThread(threading.Thread):
    """消费者线程：处理HTTP请求"""

    def __init__(self, worker_id: int, config: AttackConfig, task_queue: TaskQueue):
        super().__init__(name=f"Consumer-{worker_id}")
        self.worker_id = worker_id
        self.config = config
        self.task_queue = task_queue
        self.session = None
        self.request_count = 0
        self.daemon = True  # 设置为守护线程

    def _create_session(self) -> requests.Session:
        """创建带重试机制的会话"""
        session = requests.Session()

        if self.config.proxy:
            session.proxies = {
                'http': self.config.proxy,
                'https': self.config.proxy
            }

        retry_strategy = Retry(
            total=self.config.retry,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _parse_cookies(self) -> Dict:
        """解析Cookie字符串"""
        if not self.config.cookies:
            return {}

        cookies = {}
        for item in self.config.cookies.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                cookies[key] = value
        return cookies

    def _check_success(self, response: requests.Response, params: Dict[str, str]) -> bool:
        """检查是否成功"""
        criteria = self.config.success_criteria

        # 如果没有设置条件，使用默认判断
        if not criteria:
            if response.status_code == 200:
                error_keywords = ['error', 'invalid', 'incorrect', 'wrong', '失败', '错误']
                response_text = response.text.lower()
                if not any(keyword in response_text for keyword in error_keywords):
                    return True
            elif response.status_code in [301, 302, 303]:
                return True
            return False

        # 检查自定义条件
        if 'status_code' in criteria:
            expected = criteria['status_code']
            if isinstance(expected, list):
                if response.status_code not in expected:
                    return False
            elif response.status_code != expected:
                return False

        if 'contains' in criteria:
            keywords = criteria['contains']
            if isinstance(keywords, str):
                keywords = [keywords]

            response_text = response.text.lower()
            for keyword in keywords:
                if keyword.lower() not in response_text:
                    return False

        if 'not_contains' in criteria:
            keywords = criteria['not_contains']
            if isinstance(keywords, str):
                keywords = [keywords]

            response_text = response.text.lower()
            for keyword in keywords:
                if keyword.lower() in response_text:
                    return False

        if 'regex' in criteria:
            pattern = criteria['regex']
            if not re.search(pattern, response.text):
                return False

        return True

    def send_request(self, params: Dict[str, str]) -> Tuple[bool, Dict]:
        """发送HTTP请求"""
        try:
            # 准备请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                **self.config.headers
            }

            # 发送请求
            if self.session is None:
                self.session = self._create_session()

            if self.config.method == 'POST':
                content_type = headers.get('Content-Type', '').lower()
                if 'application/json' in content_type:
                    response = self.session.post(
                        self.config.url,
                        json=params,
                        headers=headers,
                        timeout=self.config.timeout,
                        cookies=self._parse_cookies(),
                        allow_redirects=True
                    )
                else:
                    response = self.session.post(
                        self.config.url,
                        data=params,
                        headers=headers,
                        timeout=self.config.timeout,
                        cookies=self._parse_cookies(),
                        allow_redirects=True
                    )
            else:  # GET, PUT, DELETE
                response = self.session.request(
                    self.config.method,
                    self.config.url,
                    params=params,
                    headers=headers,
                    timeout=self.config.timeout,
                    cookies=self._parse_cookies(),
                    allow_redirects=True
                )

            # 检查是否成功
            success = self._check_success(response, params)

            result = {
                'worker_id': self.worker_id,
                'params': params,
                'status_code': response.status_code,
                'success': success,
                'response_length': len(response.text),
                'response_time': response.elapsed.total_seconds(),
                'timestamp': time.time()
            }

            return success, result

        except Exception as e:
            return False, {
                'worker_id': self.worker_id,
                'params': params,
                'error': str(e),
                'success': False,
                'timestamp': time.time()
            }

    def run(self):
        """运行消费者"""
        try:
            if self.config.verbose:
                print(f"{Fore.YELLOW}[消费者{self.worker_id}] 启动{Style.RESET_ALL}")

            idle_count = 0
            max_idle_count = 10  # 连续空闲次数阈值

            while not self.task_queue.is_stopped():
                # 获取任务
                task = self.task_queue.get_task(timeout=1)
                if task is None:
                    # 检查是否需要退出
                    if (self.task_queue.producer_finished.is_set() and
                        self.task_queue.task_queue.empty()):
                        if self.config.verbose:
                            print(f"{Fore.YELLOW}[消费者{self.worker_id}] 生产者已结束，队列为空，退出{Style.RESET_ALL}")
                        break
                    idle_count += 1
                    if idle_count > max_idle_count:
                        # 等待一段时间后重试
                        time.sleep(0.5)
                        idle_count = 0
                    continue

                idle_count = 0

                try:
                    # 发送请求
                    success, result = self.send_request(task)
                    self.request_count += 1

                    # 更新统计
                    with self.task_queue.stats_lock:
                        self.task_queue.stats['tasks_processed'] += 1
                        self.task_queue.stats['requests_sent'] += 1
                        if success:
                            self.task_queue.stats['tasks_success'] += 1
                        else:
                            self.task_queue.stats['tasks_failed'] += 1

                    # 将结果放入结果队列
                    if not self.task_queue.put_result(result):
                        if self.task_queue.is_stopped():
                            break

                    # 延迟
                    if self.config.delay > 0:
                        time.sleep(self.config.delay / 1000.0)

                except KeyboardInterrupt:
                    print(f"{Fore.YELLOW}[消费者{self.worker_id}] 收到键盘中断{Style.RESET_ALL}")
                    break
                except Exception as e:
                    if not self.task_queue.is_stopped():
                        if self.config.verbose:
                            print(f"{Fore.RED}[消费者{self.worker_id}] 处理任务失败: {e}{Style.RESET_ALL}")
                finally:
                    # 标记任务完成
                    self.task_queue.task_done()

            if self.config.verbose:
                print(f"{Fore.YELLOW}[消费者{self.worker_id}] 处理完成，发送了 {self.request_count} 个请求{Style.RESET_ALL}")

        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"{Fore.RED}[消费者{self.worker_id}] 运行时错误: {e}{Style.RESET_ALL}")
            traceback.print_exc()
        finally:
            # 关闭会话
            if self.session:
                self.session.close()


class ResultProcessorThread(threading.Thread):
    """结果处理线程"""

    def __init__(self, config: AttackConfig, task_queue: TaskQueue,
                 total_tasks: int, progress_bar: tqdm = None):
        super().__init__(name=f"ResultProcessor-{threading.get_ident()}")
        self.config = config
        self.task_queue = task_queue
        self.total_tasks = total_tasks
        self.progress_bar = progress_bar
        self.success_results = []
        self.all_results = []
        self.processed_count = 0
        self.daemon = True  # 设置为守护线程

    def run(self):
        """运行结果处理器"""
        try:
            if self.config.verbose:
                print(f"{Fore.GREEN}[结果处理器] 启动{Style.RESET_ALL}")

            idle_count = 0
            max_idle_count = 20  # 增加空闲次数阈值

            while not self.task_queue.is_stopped():
                # 获取结果
                result = self.task_queue.get_result(timeout=0.5)
                if result is None:
                    # 检查是否需要退出
                    if (self.task_queue.producer_finished.is_set() and
                        self.task_queue.consumers_finished.is_set() and
                        self.task_queue.result_queue.empty()):
                        if self.config.verbose:
                            print(f"{Fore.GREEN}[结果处理器] 生产者和消费者都已结束，结果队列为空，退出{Style.RESET_ALL}")
                        break
                    idle_count += 1
                    if idle_count > max_idle_count:
                        # 额外检查：如果所有队列都为空且线程已标记结束，则退出
                        task_qsize, result_qsize, _ = self.task_queue.get_queue_status()
                        if task_qsize == 0 and result_qsize == 0:
                            if self.config.verbose:
                                print(f"{Fore.GREEN}[结果处理器] 所有队列为空，退出{Style.RESET_ALL}")
                            break
                        idle_count = 0
                    continue

                idle_count = 0

                try:
                    self.processed_count += 1

                    # 更新进度条
                    if self.progress_bar:
                        self.progress_bar.update(1)

                    # 保存结果
                    if self.config.save_all:
                        self.all_results.append(result)

                    if result.get('success'):
                        self.success_results.append(result)

                        if not self.config.quiet and self.config.show_success:
                            param_str = ", ".join([f"{k}={v}" for k, v in result['params'].items()])
                            print(
                                f"{Fore.GREEN}[+] 成功: {param_str} (状态码: {result.get('status_code', 'N/A')}){Style.RESET_ALL}")

                except KeyboardInterrupt:
                    print(f"{Fore.YELLOW}[结果处理器] 收到键盘中断{Style.RESET_ALL}")
                    break
                except Exception as e:
                    if not self.task_queue.is_stopped():
                        print(f"{Fore.RED}[结果处理器] 处理结果失败: {e}{Style.RESET_ALL}")
                finally:
                    # 标记结果处理完成
                    self.task_queue.result_done()

            if self.config.verbose:
                print(f"{Fore.GREEN}[结果处理器] 处理完成，共处理 {self.processed_count} 个结果{Style.RESET_ALL}")

        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"{Fore.RED}[结果处理器] 运行时错误: {e}{Style.RESET_ALL}")
            traceback.print_exc()


class QueueBasedAttacker:
    """基于队列的攻击器"""

    def __init__(self, config: AttackConfig):
        self.config = config
        self.task_queue = TaskQueue(config)
        self.producer = None
        self.consumers = []
        self.result_processor = None
        self.progress_bar = None
        self._interrupted = False
        self._stop_flag = threading.Event()

    def _interrupt_handler(self, signum, frame):
        """中断处理"""
        if not self._interrupted:
            self._interrupted = True
            print(f"\n{Fore.YELLOW}[!] 收到中断信号，正在停止...{Style.RESET_ALL}")
            self._stop_all_threads()
            self._stop_flag.set()

    def _stop_all_threads(self):
        """停止所有线程"""
        if self.config.verbose:
            print(f"{Fore.YELLOW}[!] 正在停止所有线程...{Style.RESET_ALL}")

        # 首先停止队列
        self.task_queue.stop()

        # 等待一小段时间让线程检测到停止信号
        time.sleep(0.5)

        # 强制终止线程（如果还在运行）
        for thread in [self.producer] + self.consumers + [self.result_processor]:
            if thread and thread.is_alive():
                if self.config.verbose:
                    print(f"{Fore.YELLOW}[!] 强制终止线程: {thread.name}{Style.RESET_ALL}")

    def _show_config(self):
        """显示配置信息"""
        print(f"{Fore.YELLOW}[*] 配置信息:{Style.RESET_ALL}")
        print(f"  目标URL: {self.config.url}")
        print(f"  请求方法: {self.config.method}")
        print(f"  线程数: {self.config.threads}")
        print(f"  输出目录: {self.config.output_dir}")
        print(f"  队列大小: {self.config.max_queue_size}")
        print(f"  批次大小: {self.config.batch_size}")
        print(f"  参数列表:")

        for param_name, param in self.config.params.items():
            values = param.get_values()
            source_type = "文件" if os.path.exists(param.source.spec) else "固定值"
            print(f"    - {param_name}: {len(values)} 个值 ({source_type})")
            if self.config.verbose and values:
                sample = values[:3]
                if len(values) > 3:
                    sample.append("...")
                print(f"      示例: {', '.join(sample)}")

        if self.config.headers:
            print(f"  自定义请求头: {len(self.config.headers)} 个")

        if self.config.success_criteria:
            print(f"  成功条件: {self.config.success_criteria}")

        print()

    def _show_results(self, duration: float):
        """显示结果"""
        stats = self.task_queue.stats

        print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}攻击完成!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")

        print(f"{Fore.YELLOW}[*] 统计信息:{Style.RESET_ALL}")
        print(f"  生成任务数: {stats.get('tasks_generated', 0):,}")
        print(f"  处理任务数: {stats.get('tasks_processed', 0):,}")
        print(f"  发送请求数: {stats.get('requests_sent', 0):,}")
        print(f"  成功任务数: {stats.get('tasks_success', 0):,}")
        print(f"  失败任务数: {stats.get('tasks_failed', 0):,}")

        if stats.get('tasks_processed', 0) > 0:
            success_rate = (stats.get('tasks_success', 0) / stats.get('tasks_processed', 1)) * 100
            print(f"  成功率: {success_rate:.2f}%")

        print(f"  总耗时: {duration:.2f} 秒")
        if duration > 0 and stats.get('tasks_processed', 0) > 0:
            speed = stats.get('tasks_processed', 0) / duration
            print(f"  平均速度: {speed:.2f} 次/秒")

        if self.result_processor and hasattr(self.result_processor, 'success_results'):
            success_count = len(self.result_processor.success_results)
            if success_count > 0:
                if self.config.show_success:
                    print(f"\n{Fore.GREEN}[+] 发现 {success_count} 个可能的成功组合!{Style.RESET_ALL}")
                    for i, result in enumerate(self.result_processor.success_results[:5]):  # 只显示前5个
                        param_str = ", ".join([f"{k}={v}" for k, v in result['params'].items()])
                        print(f"  {i + 1}. {param_str} (状态码: {result.get('status_code', 'N/A')})")

                    if len(self.result_processor.success_results) > 5:
                        print(f"  ... 还有 {len(self.result_processor.success_results) - 5} 个成功组合")
            else:
                if not self.config.quiet:
                    print(f"\n{Fore.RED}[-] 未发现成功组合{Style.RESET_ALL}")

    def _save_results(self):
        """保存结果到文件"""
        try:
            # 如果不保存结果，直接返回
            if not self.config.save_results:
                return

            if not self.result_processor or not hasattr(self.result_processor, 'success_results'):
                return

            # 创建输出目录
            os.makedirs(self.config.output_dir, exist_ok=True)

            # 保存成功结果到固定文件
            success_file = os.path.join(self.config.output_dir, "brute_force_results.txt")
            with open(success_file, 'w', encoding='utf-8') as f:
                f.write(f"成功结果报告\n")
                f.write(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"目标URL: {self.config.url}\n")
                f.write(f"请求方法: {self.config.method}\n")
                f.write(f"总尝试次数: {self.task_queue.stats.get('tasks_processed', 0)}\n")
                f.write(f"成功次数: {self.task_queue.stats.get('tasks_success', 0)}\n\n")

                if self.result_processor.success_results:
                    f.write(f"成功组合列表:\n")
                    f.write(f"{'=' * 120}\n")
                    
                    # 计算各列的最大宽度
                    max_param_width = 0
                    for result in self.result_processor.success_results:
                        param_str = ", ".join([f"{k}={v}" for k, v in result['params'].items()])
                        max_param_width = max(max_param_width, len(param_str))
                    
                    # 格式化输出每个结果
                    for i, result in enumerate(self.result_processor.success_results, 1):
                        param_str = ", ".join([f"{k}={v}" for k, v in result['params'].items()])
                        status_code = str(result.get('status_code', 'N/A'))
                        response_length = str(result.get('response_length', 0))
                        response_time = f"{result.get('response_time', 0):.3f}秒"
                        
                        f.write(f"[{i:2d}] {param_str:<{max_param_width}} | 状态码: {status_code:<5} | "
                               f"响应长度: {response_length:<4} | 响应时间: {response_time}\n")
                    
                    f.write(f"{'=' * 120}\n")
                else:
                    f.write(f"无成功组合\n")

            if not self.config.quiet:
                print(f"{Fore.GREEN}[+] 成功结果已保存到: {success_file}{Style.RESET_ALL}")

            # 保存所有结果（如果启用）
            if self.config.save_all and hasattr(self.result_processor, 'all_results'):
                all_file = os.path.join(self.config.output_dir, "all_results.json")
                with open(all_file, 'w', encoding='utf-8') as f:
                    json.dump(self.result_processor.all_results, f, ensure_ascii=False, indent=2)

                if not self.config.quiet:
                    print(f"{Fore.GREEN}[+] 所有结果已保存到: {all_file}{Style.RESET_ALL}")

            # 保存统计信息
            stats_file = os.path.join(self.config.output_dir, "statistics.json")
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.task_queue.stats, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"{Fore.RED}[!] 保存结果失败: {e}{Style.RESET_ALL}")
            traceback.print_exc()

    def _monitor_progress(self):
        """监控进度（仅用于状态监控，不更新进度条）"""
        while not self._stop_flag.is_set():
            # 获取队列状态用于内部监控
            task_qsize, result_qsize, _ = self.task_queue.get_queue_status()
            
            # 只在详细模式下输出状态
            if self.config.verbose and not self.config.quiet:
                print(f"\r[监控] 任务队列={task_qsize} 结果队列={result_qsize}", end='', flush=True)

            time.sleep(2)  # 每2秒更新一次

    def run(self):
        """运行攻击"""
        print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}多参数暴力破解工具 v4.2 (生产者消费者队列版) 修复版本{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")

        # 显示配置
        self._show_config()

        # 计算总组合数
        total_combinations = self.config.get_total_combinations()

        if total_combinations == 0:
            print(f"{Fore.RED}[!] 没有生成任何组合{Style.RESET_ALL}")
            return

        print(f"{Fore.YELLOW}[*] 总组合数: {total_combinations:,}{Style.RESET_ALL}")

        # 检查组合数是否过大
        if total_combinations > 1000000:
            print(f"{Fore.YELLOW}[!] 警告: 组合数超过100万，可能会消耗较长时间{Style.RESET_ALL}")
            if not self.config.quiet:
                response = input(f"{Fore.YELLOW}[?] 是否继续? (y/N): {Style.RESET_ALL}")
                if response.lower() != 'y':
                    print(f"{Fore.YELLOW}[*] 已取消{Style.RESET_ALL}")
                    return

        # 设置开始时间
        self.task_queue.stats['start_time'] = time.time()

        # 注册中断处理器
        original_sigint = signal.signal(signal.SIGINT, self._interrupt_handler)

        try:
            print(f"{Fore.GREEN}[+] 开始攻击...{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}[提示] 按 Ctrl+C 可随时停止程序{Style.RESET_ALL}")

            # 创建进度条
            if not self.config.quiet:
                self.progress_bar = tqdm(
                    total=total_combinations,
                    desc="攻击进度",
                    unit="次",
                    dynamic_ncols=True
                )

            # 创建并启动生产者
            self.producer = ProducerThread(self.config, self.task_queue)
            self.producer.start()

            # 创建并启动消费者
            for i in range(self.config.threads):
                consumer = ConsumerThread(i + 1, self.config, self.task_queue)
                consumer.start()
                self.consumers.append(consumer)

            # 创建并启动结果处理器
            self.result_processor = ResultProcessorThread(
                self.config, self.task_queue, total_combinations, self.progress_bar
            )
            self.result_processor.start()

            # 只在详细模式下启动进度监控线程
            if self.config.verbose and not self.config.quiet:
                monitor_thread = threading.Thread(target=self._monitor_progress, daemon=True)
                monitor_thread.start()

            # 等待生产者完成
            if self.producer.is_alive():
                self.producer.join(timeout=5)

            # 等待消费者完成（增加超时时间）
            for consumer in self.consumers:
                if consumer.is_alive():
                    consumer.join(timeout=5)

            # 标记所有消费者已结束
            self.task_queue.consumers_finished.set()

            # 等待结果处理器完成
            if self.result_processor.is_alive():
                self.result_processor.join(timeout=5)

            # 设置结束时间
            self.task_queue.stats['end_time'] = time.time()

            # 计算持续时间
            duration = self.task_queue.stats['end_time'] - self.task_queue.stats['start_time']

            # 显示结果
            self._show_results(duration)

            # 保存结果
            self._save_results()

        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}[!] 收到键盘中断信号{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[!] 运行错误: {e}{Style.RESET_ALL}")
            traceback.print_exc()
        finally:
            # 恢复原始信号处理器
            signal.signal(signal.SIGINT, original_sigint)

            # 设置停止标志
            self._stop_flag.set()

            # 确保所有线程都已停止
            self._stop_all_threads()

            # 关闭进度条，确保清除显示
            if self.progress_bar:
                self.progress_bar.clear()
                self.progress_bar.close()


# 主函数保持不变（同原代码）
def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='多参数暴力破解工具 v4.2 (生产者消费者队列版) 修复版本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
参数格式说明:
  1. 从文件读取: username=users.txt
  2. 固定单个值: username=admin
  3. 多个固定值: username=admin,root,test
  4. 混合使用: param1=value1,value2 & param2=dict.txt

示例:
  # 双参数爆破（文件+固定值）
  %(prog)s -u http://target.com/login -p "username=users.txt" -p "password=admin123"

  # 三参数爆破（混合模式）
  %(prog)s -u http://api.com/auth \\
           -p "email=admin@test.com,user@test.com" \\
           -p "password=passwords.txt" \\
           -p "token=abc123"

  # GET请求，固定值
  %(prog)s -u http://target.com/search -m GET \\
           -p "q=keyword1,keyword2,keyword3" \\
           -p "page=1,2,3,4,5"

  # 控制队列大小
  %(prog)s -u http://target.com/login -p "u=users.txt" -p "p=passwords.txt" \\
           -t 20 --queue-size 5000
        '''
    )

    # 必需参数
    parser.add_argument('-u', '--url', required=True, help='目标URL')
    parser.add_argument('-p', '--param', action='append', required=True,
                        help='参数定义: 参数名=值来源 (可多次使用)')

    # 请求配置
    parser.add_argument('-m', '--method', choices=['GET', 'POST', 'PUT', 'DELETE'],
                        default='POST', help='请求方法')
    parser.add_argument('-t', '--threads', type=int, default=5, help='线程数')
    parser.add_argument('-to', '--timeout', type=int, default=10, help='超时时间(秒)')
    parser.add_argument('-r', '--retry', type=int, default=3, help='重试次数')
    parser.add_argument('-d', '--delay', type=float, default=0, help='请求延迟(毫秒)')

    # 队列配置
    parser.add_argument('--queue-size', type=int, default=1000,
                        help='任务队列大小 (默认: 1000)')
    parser.add_argument('--batch-size', type=int, default=100,
                        help='批次大小 (默认: 100)')

    # 请求头
    parser.add_argument('-H', '--header', action='append', help='自定义请求头: "名称: 值"')
    parser.add_argument('--cookie', help='Cookie字符串')
    parser.add_argument('--proxy', help='代理服务器')

    # 成功条件
    parser.add_argument('--success-status', type=int, help='成功状态码')
    parser.add_argument('--success-contains', help='成功响应包含的文本')
    parser.add_argument('--success-not-contains', help='成功响应不包含的文本')
    parser.add_argument('--success-regex', help='成功响应正则表达式')

    # 输出配置
    parser.add_argument('-o', '--output', default='results', help='输出目录')
    parser.add_argument('--save-all', action='store_true', help='保存所有结果')
    parser.add_argument('-v', '--verbose', action='store_true', help='详细输出')
    parser.add_argument('-q', '--quiet', action='store_true', help='安静模式')

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_arguments()

    # 解析参数定义
    params = {}
    for param_spec in args.param:
        if '=' not in param_spec:
            print(f"{Fore.RED}[!] 参数格式错误: {param_spec}，应该是 参数名=值来源{Style.RESET_ALL}")
            sys.exit(1)

        name, source_spec = param_spec.split('=', 1)
        name = name.strip()
        source_spec = source_spec.strip()

        if not name or not source_spec:
            print(f"{Fore.RED}[!] 参数名和值来源都不能为空: {param_spec}{Style.RESET_ALL}")
            sys.exit(1)

        source = ParameterSource(source_spec)
        param_config = ParamConfig(name, source)

        # 检查是否有值
        values = param_config.get_values()
        if not values:
            print(f"{Fore.YELLOW}[!] 警告: 参数 '{name}' 没有可用值{Style.RESET_ALL}")

        params[name] = param_config

    # 解析请求头
    headers = {}
    if args.header:
        for header in args.header:
            if ':' in header:
                name, value = header.split(':', 1)
                headers[name.strip()] = value.strip()

    # 解析成功条件
    success_criteria = {}
    if args.success_status:
        success_criteria['status_code'] = args.success_status
    if args.success_contains:
        success_criteria['contains'] = args.success_contains
    if args.success_not_contains:
        success_criteria['not_contains'] = args.success_not_contains
    if args.success_regex:
        success_criteria['regex'] = args.success_regex

    # 创建配置
    config = AttackConfig(
        url=args.url,
        method=args.method,
        params=params,
        threads=args.threads,
        timeout=args.timeout,
        retry=args.retry,
        delay=args.delay,
        proxy=args.proxy,
        cookies=args.cookie,
        headers=headers,
        success_criteria=success_criteria,
        output_dir=args.output,
        verbose=args.verbose,
        quiet=args.quiet,
        save_all=args.save_all,
        max_queue_size=args.queue_size,
        batch_size=args.batch_size
    )

    try:
        # 运行攻击
        attacker = QueueBasedAttacker(config)
        attacker.run()

    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[!] 程序被用户终止{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as e:
        print(f"{Fore.RED}[!] 错误: {e}{Style.RESET_ALL}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()