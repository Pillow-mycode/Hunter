"""
数据分析员模块
负责分析超长命令输出，提取关键信息
"""

import os
from typing import Optional

from agent.pojo.analyst_config import DataAnalystConfig
from agent.team.agent_base import AgentBase
from agent.system.output_handler import clean_ansi_codes, save_output_to_file
from agent.team.protocol import MSG_ANALYSIS_RESULT

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DataAnalyst(AgentBase):
    AGENT_ID = "data_analyst"

    def __init__(self, config: DataAnalystConfig = None, comm_bus=None, blackboard=None, agent_id: str = ""):
        self.config = config or DataAnalystConfig()
        self.system_prompt = self.config.system_prompt
        if comm_bus and blackboard:
            super().__init__(comm_bus, blackboard, agent_id=agent_id)

    def _call_llm(self, content: str) -> str:
        """调用 LLM 分析内容"""
        try:
            print(f"[数据分析员] 正在分析 {len(content)} 字符的输出...")

            result = self.config.provider.chat([
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请分析以下渗透测试工具的输出，提取关键信息：\n\n{content}"}
            ])
            print(f"[数据分析员] 分析完成")
            return result

        except Exception as e:
            print(f"[数据分析员] 分析失败: {e}")
            return f"分析失败: {str(e)}"

    def _split_into_batches(self, text: str) -> list:
        """将文本按行分批，每批不超过 max_input_chars"""
        lines = text.split('\n')
        batches = []
        current_batch = []
        current_length = 0

        for line in lines:
            line_length = len(line) + 1  # +1 for newline

            if current_length + line_length > self.config.batch_size:
                # 当前批次已满，保存并开始新批次
                if current_batch:
                    batches.append('\n'.join(current_batch))
                current_batch = [line]
                current_length = line_length
            else:
                current_batch.append(line)
                current_length += line_length

        # 保存最后一批
        if current_batch:
            batches.append('\n'.join(current_batch))

        return batches

    def _merge_summaries(self, summaries: list) -> str:
        """汇总多个批次的分析结果"""
        if len(summaries) == 1:
            return summaries[0]

        # 将所有摘要合并，让 LLM 做最终汇总
        combined = "\n\n---\n\n".join([f"【第 {i+1} 部分分析结果】\n{s}" for i, s in enumerate(summaries)])

        try:
            print(f"[数据分析员] 正在汇总 {len(summaries)} 个批次的结果...")

            result = self.config.provider.chat([
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"以下是对一个大型输出分批分析的结果，请汇总这些结果，生成一个完整的总结：\n\n{combined}"}
            ])
            print(f"[数据分析员] 汇总完成")
            return result

        except Exception as e:
            print(f"[数据分析员] 汇总失败: {e}")
            # 汇总失败时，直接拼接各部分结果
            return "\n\n".join(summaries)

    def analyze(self, output: str, command: str = "", task_id: str = "default") -> tuple:
        """
        分析命令输出

        Args:
            output: 命令输出
            command: 执行的命令（用于保存文件）
            task_id: 任务 ID（用于保存文件）

        Returns:
            (分析结果, 完整输出文件路径 或 None)
        """
        # 清理 ANSI 转义序列
        cleaned_output = clean_ansi_codes(output)

        # 如果输出不超过阈值，直接返回
        if len(cleaned_output) <= self.config.trigger_threshold:
            return cleaned_output, None

        # 保存完整输出到文件
        file_path = save_output_to_file(output, command, task_id)
        print(f"[数据分析员] 输出过长({len(cleaned_output)}字符)，完整结果已保存到: {file_path}")

        # 判断是否需要分批
        if len(cleaned_output) <= self.config.max_input_chars:
            # 不需要分批，一次性分析
            summary = self._call_llm(cleaned_output)
        else:
            # 需要分批处理
            batches = self._split_into_batches(cleaned_output)
            print(f"[数据分析员] 输出过长，分 {len(batches)} 批处理")

            # 分批分析
            summaries = []
            for i, batch in enumerate(batches):
                print(f"[数据分析员] 处理第 {i+1}/{len(batches)} 批 ({len(batch)} 字符)")
                batch_summary = self._call_llm(batch)
                summaries.append(batch_summary)

            # 汇总结果
            summary = self._merge_summaries(summaries)

        # 构建最终输出
        result = (
            f"[数据分析员报告]\n"
            f"原始输出: {len(cleaned_output)} 字符\n"
            f"完整结果已保存到: {file_path}\n"
            f"\n"
            f"【分析摘要】\n"
            f"{summary}"
        )

        return result, file_path


    def decide(self, context: dict) -> dict:
        if self._abort_event and self._abort_event.is_set():
            return {"type": "wait"}

        msgs = self.drain_inbox()
        for msg in msgs:
            if self._abort_event and self._abort_event.is_set():
                break
            if msg.msg_type == "analysis_request":
                self.update_my_status("busy")
                output = msg.context_json.get("output", "") if msg.context_json else msg.content
                result, file_path = self.analyze(output, task_id=msg.task_id or "default")
                if self._abort_event and self._abort_event.is_set():
                    break
                self.send_msg(
                    to=msg.from_agent,
                    msg_type=MSG_ANALYSIS_RESULT,
                    content=result,
                    reply_to=msg.msg_id,
                    context_json={"file_path": file_path} if file_path else None,
                )
                self.update_my_status("idle")
        return {"type": "wait"}


# 全局实例（延迟初始化）
_analyst_instance: Optional[DataAnalyst] = None


def get_data_analyst() -> DataAnalyst:
    """获取数据分析员实例"""
    global _analyst_instance
    if _analyst_instance is None:
        _analyst_instance = DataAnalyst()
    return _analyst_instance


def analyze_long_output(output: str, command: str = "", task_id: str = "default") -> tuple:
    """
    分析超长输出的便捷函数

    Args:
        output: 命令输出
        command: 执行的命令
        task_id: 任务 ID

    Returns:
        (分析结果, 文件路径 或 None)
    """
    analyst = get_data_analyst()
    return analyst.analyze(output, command, task_id)
