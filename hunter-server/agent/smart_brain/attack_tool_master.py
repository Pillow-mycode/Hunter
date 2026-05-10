import json
import os
import tempfile
import threading

from agent.pojo.attack_config import AttackToolMasterConfig
from agent.system.system_command import write_to_logs, sys_shell
from agent.system.output_handler import process_long_output

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""
武器大师模型
改造后支持结构化输入输出
"""


class AttackToolMaster:
    def __init__(self, config: AttackToolMasterConfig):
        self.messages = []
        self.tools = config.tools
        self.config = config
        self.messages.append({"role": "system", "content": self.config.system_prompt})
        self.messages_lock = threading.Lock()

        # 当前任务信息
        self.current_task = None
        self.current_task_id = None  # 用于文件保存

        # 进度回调（用于向客户端发送消息）
        self.on_progress = None
        # 用户输入回调（用于向用户询问输入）
        self.on_need_input = None

    def _notify_progress(self, message: str):
        """发送进度通知到客户端"""
        if self.on_progress:
            self.on_progress(message)
        print(message)

    def _get_install_command(self, tool_name: str) -> str:
        """获取外部工具的安装命令"""
        # 外部工具安装命令映射表
        install_commands = {
            # 扫描工具
            "rustscan": "sudo apt update && sudo apt install -y rustscan || cargo install rustscan",
            "feroxbuster": "sudo apt update && sudo apt install -y feroxbuster",
            "dirsearch": "sudo apt update && sudo apt install -y dirsearch || pip install dirsearch",
            "nuclei": "go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest || sudo apt install -y nuclei",
            "subfinder": "go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest || sudo apt install -y subfinder",
            "httpx": "go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest || sudo apt install -y httpx",
            "katana": "go install github.com/projectdiscovery/katana/cmd/katana@latest",

            # 漏洞扫描
            "testssl.sh": "sudo apt update && sudo apt install -y testssl.sh || git clone --depth 1 https://github.com/drwetter/testssl.sh.git /opt/testssl.sh",
            "nikto": "sudo apt update && sudo apt install -y nikto",

            # 密码工具
            "hashcat": "sudo apt update && sudo apt install -y hashcat",

            # 后渗透
            "bloodhound": "sudo apt update && sudo apt install -y bloodhound",
            "evil-winrm": "sudo gem install evil-winrm",
            "crackmapexec": "sudo apt update && sudo apt install -y crackmapexec || pipx install crackmapexec",

            # 其他工具
            "gobuster": "sudo apt update && sudo apt install -y gobuster",
            "ffuf": "sudo apt update && sudo apt install -y ffuf",
            "seclists": "sudo apt update && sudo apt install -y seclists",
            "wordlists": "sudo apt update && sudo apt install -y wordlists",

            # Python 工具
            "impacket": "pip install impacket || pipx install impacket",
            "pwntools": "pip install pwntools",

            # Go 工具通用安装
            "amass": "sudo apt update && sudo apt install -y amass",
            "assetfinder": "go install github.com/tomnomnom/assetfinder@latest",
            "waybackurls": "go install github.com/tomnomnom/waybackurls@latest",
            "gau": "go install github.com/lc/gau/v2/cmd/gau@latest",
            "anew": "go install github.com/tomnomnom/anew@latest",
        }

        return install_commands.get(tool_name.lower(), "")

    def get_response(self, messages):
        """获取LLM响应，带智能截断和重试机制"""
        max_total_length = 200000
        current_length = sum(len(str(msg.get("content", ""))) for msg in messages)

        if current_length > max_total_length:
            print(f"警告: 消息总长度({current_length}字符)超出限制，开始智能截断...")

            system_messages = [msg for msg in messages if msg["role"] == "system"]
            other_messages = [msg for msg in messages if msg["role"] != "system"]
            truncated_messages = []
            accumulated_length = sum(len(str(msg.get("content", ""))) for msg in system_messages)

            for msg in reversed(other_messages):
                msg_length = len(str(msg.get("content", "")))
                if accumulated_length + msg_length > max_total_length:
                    break
                truncated_messages.append(msg)
                accumulated_length += msg_length

            messages = system_messages + list(reversed(truncated_messages))

            if len(messages) < len(system_messages) + len(other_messages):
                tip = {
                    "role": "system",
                    "content": f"[系统提示: 由于内容过长，已截断历史消息。当前保留了{len(messages)}条消息。]"
                }
                messages.append(tip)

            print(f"截断后: {len(messages)}条消息，{accumulated_length}字符")

        final_length = sum(len(str(msg.get("content", ""))) for msg in messages)
        if final_length > 250000:
            print(f"错误: 即使截断后仍然过长({final_length}字符)，强制截断...")
            messages = [msg for msg in messages if msg["role"] == "system"][-2:] + \
                       [msg for msg in messages if msg["role"] != "system"][-3:]

        # 重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.config.provider.chat(messages)
            except Exception as e:
                error_msg = str(e)
                print(f"武器大师 API 调用失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")

                if "input length" in error_msg.lower():
                    # 输入长度超限，不重试
                    return json.dumps({"type": "error", "content": f"API调用失败: 输入长度超限。{error_msg}"})

                if attempt < max_retries - 1:
                    # 还有重试机会
                    import time
                    wait_time = (attempt + 1) * 2
                    print(f"武器大师: {wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    # 最后一次尝试也失败了
                    return json.dumps({"type": "error", "content": f"API调用失败（已重试{max_retries}次）: {error_msg}"})
            else:
                raise e

    def run(self, task: dict) -> dict:
        """
        执行任务（结构化输入输出）

        Args:
            task: 结构化任务
                {
                    "task_id": "任务ID",
                    "action": "动作名称",
                    "target": "目标",
                    "params": {}
                }

        Returns:
            结构化结果
                {
                    "task_id": "任务ID",
                    "status": "success/failed/need_input",
                    "raw_output": "原始输出",
                    "summary": "简短摘要",
                    "findings": {}
                }
        """
        self.current_task = task
        task_id = task.get("task_id", "unknown")
        self.current_task_id = task_id  # 保存用于文件命名

        # 检查是否是自然语言指令
        params = task.get('params', {})
        instruction = params.get('instruction', '')

        if instruction:
            # 自然语言指令模式
            task_description = f"""
执行任务:
- 任务ID: {task_id}
- 指令: {instruction}
- 目标: {task.get('target', '')}

请理解这个指令，选择合适的工具完成任务，完成后返回结果。
"""
        else:
            # 传统结构化模式（向后兼容）
            task_description = f"""
执行任务:
- 任务ID: {task_id}
- 动作: {task.get('action', '')}
- 目标: {task.get('target', '')}
- 参数: {json.dumps(params, ensure_ascii=False)}

请选择合适的工具完成此任务，完成后返回结果。
"""

        # 检查输入长度
        if len(task_description) > 50000:
            print(f"警告: 任务描述过长({len(task_description)}字符)，已截断")
            task_description = task_description[:50000] + "\n\n[注意: 输入内容过长，已被截断]"

        self.append_message("user", task_description)

        my_round = 0
        max_rounds = 50  # 防止无限循环

        while my_round < max_rounds:
            my_round += 1
            write_to_logs(f"武器大师第{my_round}轮:")

            json_string = self.get_response(self.messages)

            # 检查错误
            try:
                check_data = json.loads(json_string)
                if check_data.get("type") == "error":
                    print(f"API错误: {json_string}")
                    self.append_message("system", f"发生错误: {json_string}")
                    continue
            except:
                pass

            self.append_message("assistant", json_string)

            try:
                response_data = json.loads(json_string)
                response_type = response_data.get("type")
                response_content = response_data.get("content")
                response_description = response_data.get("description", "")

                if response_type == "check_tools":
                    write_to_logs("武器大师: 查看所有工具")
                    print(f"武器大师: {response_description}")
                    tools_json = json.dumps(self.tools, ensure_ascii=False, indent=2)
                    self.append_message("system", tools_json)
                    write_to_logs(f"system: {tools_json.strip()}")
                    continue

                elif response_type == "read_tool_doc":
                    tool_name = response_content
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 阅读工具文档 - {tool_name}")

                    # 查找工具文档
                    doc_path = None
                    if tool_name.endswith('.py'):
                        # 去掉 .py 后缀
                        tool_name_base = tool_name[:-3]
                        doc_path = os.path.join(PROJECT_ROOT, "tools", "tools_readme", f"{tool_name_base}.txt")
                    else:
                        doc_path = os.path.join(PROJECT_ROOT, "tools", "tools_readme", f"{tool_name}.txt")

                    try:
                        if os.path.exists(doc_path):
                            with open(doc_path, 'r', encoding='utf-8') as f:
                                doc_content = f.read()

                            write_to_logs(f"system: 工具文档内容:{doc_content[:500]}...")

                            if len(doc_content) > 50000:
                                print(f"警告: 文档内容过长({len(doc_content)}字符)，已截断")
                                doc_content = doc_content[:50000] + "\n\n[注意: 文档内容过长，已被截断]"

                            self.append_message("system", f"工具文档 ({tool_name}):\n\n{doc_content}")
                        else:
                            error_msg = f"错误: 找不到工具文档 {doc_path}"
                            print(error_msg)
                            write_to_logs(error_msg)
                            self.append_message("system", error_msg)
                    except Exception as e:
                        error_msg = f"错误: 读取工具文档失败 - {str(e)}"
                        print(error_msg)
                        write_to_logs(error_msg)
                        self.append_message("system", error_msg)
                    continue

                elif response_type == "check_tool_installed":
                    tool_name = response_content
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 检查工具是否已安装 - {tool_name}")

                    # 使用 which 命令检查工具是否已安装
                    check_result = sys_shell(f"which {tool_name} 2>/dev/null || echo 'NOT_INSTALLED'")
                    if not isinstance(check_result, str):
                        check_result = str(check_result)

                    if "NOT_INSTALLED" in check_result or not check_result.strip():
                        result_msg = f"工具 {tool_name} 未安装"
                        write_to_logs(f"system: {result_msg}")
                        self.append_message("system", result_msg)
                    else:
                        result_msg = f"工具 {tool_name} 已安装，路径: {check_result.strip()}"
                        write_to_logs(f"system: {result_msg}")
                        self.append_message("system", result_msg)
                    continue

                elif response_type == "install_tool":
                    tool_name = response_content
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 安装工具 - {tool_name}")
                    self._notify_progress(f"[武器大师] 正在安装工具: {tool_name}")

                    # 查找工具的安装命令
                    install_cmd = self._get_install_command(tool_name)
                    if install_cmd:
                        results = sys_shell(install_cmd)
                        if not isinstance(results, str):
                            results = str(results)

                        write_to_logs(f"system: 安装结果:{results[:500]}...")

                        # 处理过长输出
                        results, file_path = process_long_output(
                            results,
                            install_cmd,
                            self.current_task_id or task_id,
                            threshold=30000
                        )

                        if file_path:
                            self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")

                        # 验证安装是否成功
                        verify_result = sys_shell(f"which {tool_name} 2>/dev/null || echo 'NOT_INSTALLED'")
                        if "NOT_INSTALLED" not in str(verify_result) and str(verify_result).strip():
                            self.append_message("system", f"工具 {tool_name} 安装成功\n安装输出:\n{results}")
                        else:
                            self.append_message("system", f"工具 {tool_name} 安装可能失败，请检查\n安装输出:\n{results}")
                    else:
                        error_msg = f"错误: 未找到工具 {tool_name} 的安装命令，请手动安装"
                        print(error_msg)
                        write_to_logs(error_msg)
                        self.append_message("system", error_msg)
                    continue

                elif response_type == "shell":
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 执行命令 - {response_content}")
                    # 向客户端发送正在运行的命令
                    self._notify_progress(f"[武器大师] 正在运行: {response_content}")
                    results = sys_shell(response_content)
                    if not isinstance(results, str):
                        results = str(results)

                    write_to_logs(f"system: 命令执行结果:{results[:500]}...")

                    # 处理过长输出：保存文件 + 智能截取
                    results, file_path = process_long_output(
                        results,
                        response_content,
                        self.current_task_id or task_id,
                        threshold=30000
                    )

                    # 如果保存了文件，通知客户端
                    if file_path:
                        self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")

                    self.append_message("system", results)
                    continue

                elif response_type == "need_message":
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: {response_content}")

                    # 返回需要用户输入的状态
                    return {
                        "task_id": task_id,
                        "status": "need_input",
                        "raw_output": "",
                        "summary": response_content,
                        "findings": {},
                        "required_input": response_content
                    }

                elif response_type == "input":
                    # 工具需要交互输入，向用户询问
                    suggested_input = response_content
                    description = response_description or "工具需要输入"

                    print(f"武器大师: 工具需要输入 - {description}")
                    write_to_logs(f"武器大师: 工具需要输入 - {description}, 建议输入: {suggested_input}")

                    # 通过回调向用户询问输入
                    if self.on_need_input:
                        prompt = f"工具需要输入：{description}\n建议输入: {suggested_input}\n请输入内容（直接回车使用建议值，输入 'skip' 跳过）："
                        user_input = self.on_need_input(prompt)

                        if user_input is None or user_input.lower() == 'skip':
                            # 用户跳过输入
                            write_to_logs(f"武器大师: 用户跳过输入")
                            self.append_message("system", "用户跳过了输入，尝试继续执行")
                            continue

                        # 如果用户直接回车，使用建议值
                        actual_input = user_input.strip() if user_input.strip() else suggested_input
                    else:
                        # 没有回调，使用建议值
                        actual_input = suggested_input

                    print(f"武器大师: 提供输入 - {actual_input}")
                    write_to_logs(f"武器大师: 提供输入 - {actual_input}")

                    from agent.system.system_command import write_input_to_active_process
                    results = write_input_to_active_process(actual_input)
                    if results:
                        write_to_logs(f"system: 继续执行结果:{results[:500]}...")
                        # 处理过长输出
                        results, file_path = process_long_output(
                            results,
                            f"input: {actual_input}",
                            self.current_task_id or task_id,
                            threshold=30000
                        )
                        if file_path:
                            self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")
                        self.append_message("system", results)
                    else:
                        write_to_logs(f"system: 没有活跃进程，输入被忽略")
                        self.append_message("system", "没有活跃进程，输入被忽略。可能需要重新运行命令。")
                    continue

                elif response_type == "generate_script":
                    script_content = response_data.get("script", "")
                    script_type = response_data.get("script_type", "python")
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 生成{script_type}脚本")

                    # 保存临时脚本
                    suffix = ".py" if script_type == "python" else ".sh"
                    with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as f:
                        f.write(script_content)
                        script_path = f.name

                    try:
                        # 执行脚本
                        if script_type == "python":
                            cmd = f"python {script_path}"
                        else:
                            cmd = f"bash {script_path}"

                        results = sys_shell(cmd)
                        if not isinstance(results, str):
                            results = str(results)

                        write_to_logs(f"system: 脚本执行结果:{results[:500]}...")

                        # 处理过长输出
                        results, file_path = process_long_output(
                            results,
                            cmd,
                            self.current_task_id or task_id,
                            threshold=30000
                        )
                        if file_path:
                            self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")

                        self.append_message("system", results)
                    finally:
                        # 删除临时脚本
                        try:
                            os.remove(script_path)
                        except:
                            pass
                    continue

                elif response_type == "task_done":
                    status = response_data.get("status", "success")
                    summary = response_data.get("summary", response_content)
                    findings = response_data.get("findings", {})

                    write_to_logs(f"武器大师: 任务完成 - {summary}")
                    print(f"武器大师: 任务完成 - {summary}")

                    # 重置对话
                    self.messages = [{"role": "system", "content": self.config.system_prompt}]
                    self.current_task = None

                    return {
                        "task_id": task_id,
                        "status": status,
                        "raw_output": response_content,
                        "summary": summary,
                        "findings": findings
                    }

                else:
                    print(f"未知的响应类型: {response_type}")
                    self.append_message("system", f"未知的响应类型: {response_type}，请使用正确的类型")
                    continue

            except json.JSONDecodeError as e:
                print(f"AI回复不是有效的JSON: {json_string}")
                print(f"JSON解析错误: {e}")
                self.append_message("system", "请以正确的JSON格式回复")
                continue
            except Exception as e:
                print(f"处理AI回复时出错: {e}")
                self.append_message("system", f"处理回复时出错: {str(e)}")
                continue

        # 超过最大轮数
        return {
            "task_id": task_id,
            "status": "failed",
            "raw_output": "",
            "summary": "执行超过最大轮数限制",
            "findings": {}
        }

    def continue_with_input(self, user_input: str) -> dict:
        """
        继续执行，提供用户输入

        Args:
            user_input: 用户提供的输入

        Returns:
            结构化结果
        """
        if not self.current_task:
            return {
                "task_id": "unknown",
                "status": "failed",
                "raw_output": "",
                "summary": "没有待处理的任务",
                "findings": {}
            }

        self.append_message("user", user_input)

        # 继续执行（复用 run 的循环逻辑）
        task_id = self.current_task.get("task_id", "unknown")
        my_round = 0
        max_rounds = 50

        while my_round < max_rounds:
            my_round += 1
            write_to_logs(f"武器大师继续第{my_round}轮:")

            json_string = self.get_response(self.messages)
            self.append_message("assistant", json_string)

            try:
                response_data = json.loads(json_string)
                response_type = response_data.get("type")
                response_content = response_data.get("content")
                response_description = response_data.get("description", "")

                # 处理逻辑与 run 相同
                if response_type == "check_tools":
                    tools_json = json.dumps(self.tools, ensure_ascii=False, indent=2)
                    self.append_message("system", tools_json)
                    continue

                elif response_type == "read_tool_doc":
                    tool_name = response_content
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 阅读工具文档 - {tool_name}")

                    doc_path = None
                    if tool_name.endswith('.py'):
                        tool_name_base = tool_name[:-3]
                        doc_path = os.path.join(PROJECT_ROOT, "tools", "tools_readme", f"{tool_name_base}.txt")
                    else:
                        doc_path = os.path.join(PROJECT_ROOT, "tools", "tools_readme", f"{tool_name}.txt")

                    try:
                        if os.path.exists(doc_path):
                            with open(doc_path, 'r', encoding='utf-8') as f:
                                doc_content = f.read()
                            if len(doc_content) > 50000:
                                doc_content = doc_content[:50000] + "\n\n[注意: 文档内容过长，已被截断]"
                            self.append_message("system", f"工具文档 ({tool_name}):\n\n{doc_content}")
                        else:
                            self.append_message("system", f"错误: 找不到工具文档 {doc_path}")
                    except Exception as e:
                        self.append_message("system", f"错误: 读取工具文档失败 - {str(e)}")
                    continue

                elif response_type == "check_tool_installed":
                    tool_name = response_content
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 检查工具是否已安装 - {tool_name}")

                    check_result = sys_shell(f"which {tool_name} 2>/dev/null || echo 'NOT_INSTALLED'")
                    if not isinstance(check_result, str):
                        check_result = str(check_result)

                    if "NOT_INSTALLED" in check_result or not check_result.strip():
                        result_msg = f"工具 {tool_name} 未安装"
                        self.append_message("system", result_msg)
                    else:
                        result_msg = f"工具 {tool_name} 已安装，路径: {check_result.strip()}"
                        self.append_message("system", result_msg)
                    continue

                elif response_type == "install_tool":
                    tool_name = response_content
                    print(f"武器大师: {response_description}")
                    write_to_logs(f"武器大师: 安装工具 - {tool_name}")
                    self._notify_progress(f"[武器大师] 正在安装工具: {tool_name}")

                    install_cmd = self._get_install_command(tool_name)
                    if install_cmd:
                        results = sys_shell(install_cmd)
                        if not isinstance(results, str):
                            results = str(results)

                        results, file_path = process_long_output(
                            results,
                            install_cmd,
                            self.current_task_id or task_id,
                            threshold=30000
                        )

                        if file_path:
                            self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")

                        verify_result = sys_shell(f"which {tool_name} 2>/dev/null || echo 'NOT_INSTALLED'")
                        if "NOT_INSTALLED" not in str(verify_result) and str(verify_result).strip():
                            self.append_message("system", f"工具 {tool_name} 安装成功\n安装输出:\n{results}")
                        else:
                            self.append_message("system", f"工具 {tool_name} 安装可能失败，请检查\n安装输出:\n{results}")
                    else:
                        self.append_message("system", f"错误: 未找到工具 {tool_name} 的安装命令，请手动安装")
                    continue

                elif response_type == "shell":
                    print(f"武器大师: {response_description}")
                    # 向客户端发送正在运行的命令
                    self._notify_progress(f"[武器大师] 正在运行: {response_content}")
                    results = sys_shell(response_content)
                    if not isinstance(results, str):
                        results = str(results)
                    # 处理过长输出
                    results, file_path = process_long_output(
                        results,
                        response_content,
                        self.current_task_id or task_id,
                        threshold=30000
                    )
                    if file_path:
                        self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")
                    self.append_message("system", results)
                    continue

                elif response_type == "need_message":
                    return {
                        "task_id": task_id,
                        "status": "need_input",
                        "raw_output": "",
                        "summary": response_content,
                        "findings": {},
                        "required_input": response_content
                    }

                elif response_type == "input":
                    # 工具需要交互输入，向用户询问
                    suggested_input = response_content
                    description = response_description or "工具需要输入"

                    print(f"武器大师: 工具需要输入 - {description}")
                    write_to_logs(f"武器大师: 工具需要输入 - {description}, 建议输入: {suggested_input}")

                    # 通过回调向用户询问输入
                    if self.on_need_input:
                        prompt = f"工具需要输入：{description}\n建议输入: {suggested_input}\n请输入内容（直接回车使用建议值，输入 'skip' 跳过）："
                        user_input = self.on_need_input(prompt)

                        if user_input is None or user_input.lower() == 'skip':
                            write_to_logs(f"武器大师: 用户跳过输入")
                            self.append_message("system", "用户跳过了输入，尝试继续执行")
                            continue

                        actual_input = user_input.strip() if user_input.strip() else suggested_input
                    else:
                        actual_input = suggested_input

                    print(f"武器大师: 提供输入 - {actual_input}")
                    write_to_logs(f"武器大师: 提供输入 - {actual_input}")

                    from agent.system.system_command import write_input_to_active_process
                    results = write_input_to_active_process(actual_input)
                    if results:
                        # 处理过长输出
                        results, file_path = process_long_output(
                            results,
                            f"input: {actual_input}",
                            self.current_task_id or task_id,
                            threshold=30000
                        )
                        if file_path:
                            self._notify_progress(f"[文件] 输出过长，完整结果已保存: {file_path}")
                        self.append_message("system", results)
                    else:
                        self.append_message("system", "没有活跃进程，输入被忽略。可能需要重新运行命令。")
                    continue

                elif response_type == "task_done":
                    status = response_data.get("status", "success")
                    summary = response_data.get("summary", response_content)
                    findings = response_data.get("findings", {})

                    self.messages = [{"role": "system", "content": self.config.system_prompt}]
                    self.current_task = None

                    return {
                        "task_id": task_id,
                        "status": status,
                        "raw_output": response_content,
                        "summary": summary,
                        "findings": findings
                    }

                else:
                    self.append_message("system", f"未知的响应类型: {response_type}")
                    continue

            except json.JSONDecodeError:
                self.append_message("system", "请以正确的JSON格式回复")
                continue
            except Exception as e:
                self.append_message("system", f"处理回复时出错: {str(e)}")
                continue

        return {
            "task_id": task_id,
            "status": "failed",
            "raw_output": "",
            "summary": "执行超过最大轮数限制",
            "findings": {}
        }

    def append_message(self, role, content):
        """添加消息到对话历史"""
        with self.messages_lock:
            self.messages.append({"role": role, "content": content})
