# Hunter 架构重构：计划驱动 + 事件唤醒 + 多实例并行

## 问题诊断

当前架构三层不匹配：
- **决策粒度**：每次只吐一个 action，而非一个计划
- **决策触发**：时间驱动（每 0.5s 盲轮询），而非事件驱动
- **Agent 模型**：1:1 类型映射，无法并行派发

根因：AgentLoop 在结果返回前反复调 LLM "下一步做什么"，LLM 被"要么继续派活，要么结束"的二元选择逼着重复生成指令。

## 目标架构

Leader 从"被时间推着走的金鱼"变成"被进度推着走的指挥官"：
- Plan 作为 LLM 决策的持久化载体，驱动状态机流转
- 只在关键分叉点调 LLM（分类、规划、回顾、偏差），其余时间按计划推进
- 支持多武器大师实例并行执行互不依赖的步骤

---

## 状态机

```
                     ┌─────────────┐
     用户消息 ──────→│ CLASSIFYING │  简单查询/闲聊
                     └──────┬──────┘  → 1步执行或直接回答 → COMPLETE
                            │ 渗透任务
                            ▼
                     ┌─────────────┐
                     │  PLANNING   │←─────────────────────┐
                     └──────┬──────┘                      │
                            │ 计划就绪                     │
                            ▼                             │
                     ┌─────────────┐                      │
                     │  EXECUTING  │─── 偏离(L0/L1/L2) ──┤
                     └──────┬──────┘                      │
                            │ 计划耗尽                    │
                            ▼                             │
                     ┌─────────────┐  需要更多步骤 ───────┘
                     │  REVIEWING  │
                     └──────┬──────┘
                            │ 目标达成
                            ▼
                     ┌─────────────┐
                     │  COMPLETE   │
                     └─────────────┘
```

### 状态说明

| 状态 | 调 LLM | 行为 |
|------|--------|------|
| CLASSIFYING | 是 | 判断请求类型（简单查询/渗透任务/闲聊） |
| PLANNING | 是 | 生成多步 Plan（DAG），含依赖关系 |
| EXECUTING | 否 | 按 DAG 派发步骤，并行执行互不依赖的步骤 |
| REVIEWING | 是 | 计划耗尽后审视结果，判断是否达成目标 |
| COMPLETE | 否 | 生成报告，结束 |

---

## 核心数据结构

```python
@dataclass
class PlanStep:
    id: str                    # "s1"
    instruction: str           # 自然语言指令
    target_agent: str          # "tool_master" | "data_analyst"
    depends_on: list[str]      # DAG 依赖边
    status: str                # PENDING → DISPATCHED → RUNNING → DONE | FAILED
    result: Optional[dict]
    dispatched_to: Optional[str]

@dataclass
class Plan:
    id: str
    goal: str
    complexity: str            # "simple" | "complex"
    steps: list[PlanStep]
    max_parallel: int
```

---

## 偏离检测（L0/L1/L2）

| 层级 | 方式 | 成本 |
|------|------|------|
| L0 | 返回码非 0 → 直接判定失败 | 零成本 |
| L1 | 关键词匹配已知错误模式 | 近零成本 |
| L2 | 轻量 LLM 判断是否偏离预期 | 一次便宜 API 调用 |

---

## Agent 池

- Agent 标识从 `Literal["leader", ...]` 改为动态 UUID 字符串
- AgentPool 管理实例生命周期（acquire / release / idle_timeout / max_total）
- CommBus 收件箱从按类型索引改为按实例 ID 索引，支持动态注册/注销

---

## 实施阶段

### P1：wait 能力 + 空转拦截（改动最小，<50 行）

**目标**：立刻解决"无限循环"问题
- Leader.decide() 在无新消息 + 有未完成任务时返回 `wait`
- AgentLoop 收到 wait 后阻塞等消息（`Queue.get(timeout=)`），不调 LLM
- CommBus 新增 `wait_for_message()` 方法

**收益**：AgentLoop 不再空转调 LLM，等待期间 CPU 占用为零

### P2：状态机 + Plan 数据结构 + 顺序执行（核心重构）

**目标**：LLM 调用次数从几十次降到 3-4 次
- Plan / PlanStep 数据类
- LeaderBrain 状态机
- generate_plan() 替代 decide_next_action()
- AgentLoop 改为"取 plan step → 派发 → 等结果 → 取下一步"
- 移除 is_mission_complete() 中的硬编码计数器

**收益**：正常流程自然走向正确结果，不需要外部拦截

### P3：AgentPool + 实例 UUID + 并行派发

**目标**：多武器大师并行执行
- AgentPool（acquire / release / idle_timeout / max_total）
- CommBus 动态注册/注销 + 实例级收件箱
- AgentId 从 Literal 改为 str
- DAG 拓扑排序验证
- 并行派发互不依赖的 step

**收益**：互不依赖的任务同时执行，总耗时明显缩短

### P4：偏离检测 + re-plan

**目标**：计划容错，执行失败时自动调整

#### 问题背景

P3 实现了按 DAG 并行派发步骤，但缺少执行过程中的偏差感知。如果 step_a "nmap 扫描 10.0.0.1" 因为目标不在线而失败，后续依赖 step_a 的步骤仍然会按 DAG 顺序执行（只是状态标记为 BLOCKED），最终整个 Plan 在"所有步骤 DONE 或 FAILED"时进入 REVIEWING。此时 LLM 看到的是一串失败，但不知道失败原因和替代方案。

更好的做法：在执行过程中尽早检测偏差，触发 REPLANNING，让 LLM 基于已知信息（为什么失败）生成替代计划。

#### 三层偏差检测

##### L0 — 返回码检测（零成本）

`result["status"]` 字段由 tool_master 在 shell 命令执行后填充：
- `"success"`（退出码 0）→ 匹配预期
- `"failed"`（退出码非 0）→ 直接标记 step FAILED

```python
def _detect_deviation_l0(self, step: PlanStep, result: dict) -> bool:
    """返回 True 表示偏离"""
    if result.get("status") == "success":
        return False
    if result.get("status") == "failed":
        return True
    # 无法判断 → 交给 L1
    return None
```

这是最基础的检测，覆盖所有命令执行失败的场景。但有些场景下退出码 0 也不代表成功（比如 nmap 扫到了 0 个端口输出 "Host is up" 但没有任何端口开放 — 退出码仍是 0）。

##### L1 — 关键词模式匹配（近零成本）

某些失败模式不出现在退出码中，但在输出文本里有明确的特征：

```python
KNOWN_FAILURE_PATTERNS = [
    # 网络层
    ("connection refused", "目标拒绝连接"),
    ("connection timed out", "连接超时"),
    ("no route to host", "无路由到目标"),
    ("host is down", "目标主机不在线"),
    ("name or service not known", "DNS 解析失败"),
    ("network is unreachable", "网络不可达"),
    
    # 权限层
    ("permission denied", "权限不足"),
    ("operation not permitted", "操作不被允许"),
    ("authentication failed", "认证失败"),
    ("access denied", "访问被拒绝"),
    
    # 工具层
    ("command not found", "工具未安装"),
    ("no such file or directory", "文件不存在"),
    ("invalid option", "参数无效"),
    ("segmentation fault", "工具崩溃"),
    
    # 目标层
    ("400 bad request", "HTTP 400"),
    ("401 unauthorized", "HTTP 401"),
    ("403 forbidden", "HTTP 403"),
    ("404 not found", "HTTP 404"),
    ("500 internal server error", "HTTP 500"),
    ("502 bad gateway", "HTTP 502"),
    ("503 service unavailable", "HTTP 503"),
]
```

```python
def _detect_deviation_l1(self, step: PlanStep, result: dict) -> Optional[tuple]:
    """返回 (True, failure_reason) 如果命中已知模式，否则 None（交给 L2）"""
    output = result.get("summary", "") + result.get("raw_output", "")
    output_lower = output.lower()
    for pattern, reason in KNOWN_FAILURE_PATTERNS:
        if pattern.lower() in output_lower:
            return True, f"[L1] {reason}: 输出匹配 '{pattern}'"
    return None, None
```

##### L2 — 轻量 LLM 判断（一次便宜 API 调用）

L0 和 L1 都无法判定时，用一个轻量 LLM 调用判断"这个结果是否符合步骤预期"：

```python
def _detect_deviation_l2(self, step: PlanStep, result: dict) -> tuple:
    """
    返回 (is_deviation: bool, reason: str)
    使用便宜的模型（如 gpt-3.5-turbo / haiku）做一次快速判断。
    """
    output = result.get("summary", "") or result.get("raw_output", "") or ""
    output_snippet = output[:2000]  # 截断，控制 token

    prompt = f"""你是渗透测试结果评估员。判断以下命令执行结果是否符合预期。

步骤目标: {step.instruction}
命令输出前 2000 字符:
---
{output_snippet}
---

判断规则:
- 如果结果达成了步骤目标 → 无偏离
- 如果结果明显失败或被阻断 → 偏离
- 如果结果部分成功但信息不足 → 偏离
- 如果无法判断 → 无偏离（宁可放过不可误判）

请用 JSON 回复: {{"is_deviation": true/false, "reason": "一句话解释"}}"""

    try:
        response = self._call_llm_lightweight(prompt)  # 使用 ANALYST 或独立的轻量 API key
        return response.get("is_deviation", False), response.get("reason", "")
    except Exception:
        # LLM 调用失败 → 乐观处理，不触发 re-plan
        return False, "L2 检测不可用，默认通过"
```

#### REPLANNING 状态

在状态机中新增 `REPLANNING` 作为 EXECUTING 和 PLANNING 之间的过渡状态：

```
EXECUTING ── 偏离检测触发 ──→ REPLANNING ──→ PLANNING（生成新 Plan）
                                      │
                                      └──→ COMPLETE（重新规划也失败了）
```

```python
# 状态机扩展
self.state: str = "idle"  # idle | classifying | planning | executing | reviewing | replanning | complete
self.replan_count: int = 0  # 防止无限重新规划
self.max_replan: int = 3    # 最多重新规划 3 次
```

#### 改动范围

##### `attack_leader.py`

**新增方法：**

1. `_detect_deviation(step, result) -> tuple[bool, str]` — 串联 L0→L1→L2，返回 (是否偏离, 原因描述)
2. `_handle_executing()` 修改 — 每个步骤结果返回时调用 `_detect_deviation()`：
   - 无偏离 → 正常标记 DONE，继续派发下一步
   - 有偏离 + `step.critical == True` → 立即进入 REPLANNING
   - 有偏离 + `step.critical == False` → 标记 FAILED，继续执行其他不依赖它的步骤
3. `_handle_replanning()` — 收集失败上下文，调用 `_generate_plan()` 重新生成 Plan：
   ```python
   def _handle_replanning(self, context: dict) -> dict:
       self.replan_count += 1
       if self.replan_count > self.max_replan:
           self.state = "complete"
           return {"type": "complete", "summary": "重新规划次数超限"}
       
       # 收集失败信息
       failed_steps = [s for s in self.active_plan.steps if s.status == "FAILED"]
       done_steps = [s for s in self.active_plan.steps if s.status == "DONE"]
       failure_context = "\n".join(
           f"- {s.id}: {s.instruction}\n  失败原因: {s.deviation_reason or '未知'}"
           for s in failed_steps
       )
       success_context = "\n".join(
           f"- {s.id}: {s.instruction}\n  结果: {(s.result_summary or '')[:120]}"
           for s in done_steps
       )
       
       # 重新生成 Plan（LLM 调用）
       new_plan = self._generate_plan(
           self._current_user_request,
           previous_plan=self.active_plan,
           additional_context=f"上一次计划失败:\n{failure_context}\n\n已成功:\n{success_context}\n请基于以上信息生成替代方案。"
       )
       self.active_plan = new_plan
       self.state = "executing"
       return self._dispatch_ready_steps()
   ```

##### `plan.py`

**PlanStep 新增字段：**
```python
@dataclass
class PlanStep:
    # ... 现有字段 ...
    critical: bool = False        # True → 失败时立即触发 re-plan
    deviation_reason: str = ""    # 偏离原因描述
```

**Plan 新增方法：**
```python
def get_failure_summary(self) -> str:
    """生成失败步骤摘要，供 LLM 重新规划使用"""
    failed = [s for s in self.steps if s.status == "FAILED"]
    if not failed:
        return ""
    return "\n".join(
        f"[{s.id}] {s.instruction} → {s.deviation_reason or '未知原因'}"
        for s in failed
    )

def get_progress_summary(self) -> str:
    """当前进度摘要"""
    total = len(self.steps)
    done = sum(1 for s in self.steps if s.status == "DONE")
    failed = sum(1 for s in self.steps if s.status == "FAILED")
    pending = total - done - failed
    return f"进度: {done}/{total} 完成, {failed} 失败, {pending} 待执行"
```

##### `leader_config.py`

**新增 prompt：**
```python
SYSTEM_REPLAN_PROMPT = """你是渗透测试规划专家。上一次计划执行出现了失败步骤。

请分析失败原因，生成一个调整后的新计划:
- 保留已成功的步骤（不需要重新执行）
- 为失败的步骤生成替代方案
- 如果目标本身不可达，考虑报告目标不可达而非继续尝试
- 调整依赖关系以适应新方案
...（输出格式与 SYSTEM_PLAN_PROMPT 一致）"""
```

#### 触发策略

| 场景 | 行为 |
|------|------|
| 非关键步骤偏离 | 标记 FAILED，跳过依赖它的步骤，继续执行其他就绪步骤 |
| 关键步骤偏离 | 立即中断所有执行中步骤，进入 REPLANNING |
| 连续 3 个步骤偏离 | 强制 REPLANNING（即使都不是 critical） |
| REPLAN 后同一步骤再次偏离 | 标记 BLOCKED_PERMANENT，不再尝试 |
| 所有步骤 FAILED | 进入 REVIEWING，由 REVIEW LLM 判断是否重新规划 |

#### 边界情况

1. **L2 LLM 调用失败**：L2 不可用时退化为 L1 判断，不阻塞执行流程
2. **重新规划死循环**：`max_replan=3` 硬限制，超过后强制进入 COMPLETE
3. **关键步骤误判**：LEADER 在 PLAN 阶段通过 LLM 标记 `critical`，如果有误，REVIEW 阶段可以补救
4. **部分成功部分失败**：REPLANNING 保留已完成步骤的结果，只重新规划失败分支
5. **Token 控制**：L2 调用截断输出到 2000 字符，使用便宜的模型，单次调用控制在 ~500 tokens

#### 验证方法

1. 启动服务端，发送"扫描 192.168.1.999 的端口"（不可达 IP）→ 观察 L1 检测到 "no route to host" → 触发 REPLANNING → LLM 报告目标不可达
2. 发送"用 nmap 扫描 localhost" 但故意卸载 nmap → 观察 L1 检测到 "command not found" → 触发 REPLANNING → LLM 建议安装 nmap 或换用其他工具
3. 发送复杂任务（如"渗透测试 example.com"）→ 观察正常流程不受影响（L0/L1/L2 都不误触发）
4. 检查 `replan_count` 上限：连续触发 3 次 REPLANNING → 观察是否正确进入 COMPLETE 而不是死循环

#### 改动文件清单

| 文件 | 改动 |
|------|------|
| `agent/smart_brain/attack_leader.py` | +`_detect_deviation()`, +`_handle_replanning()`, 修改 `_handle_executing()`, +`replan_count`/`max_replan` |
| `agent/team/plan.py` | PlanStep +`critical`, +`deviation_reason`; Plan +`get_failure_summary()`, +`get_progress_summary()` |
| `agent/pojo/leader_config.py` | +`SYSTEM_REPLAN_PROMPT` |
| `agent/team/agent_loop.py` | 无需改动（replanning 是 Leader 内部状态，AgentLoop 无感知） |

不改的文件：`agent_pool.py`、`comm_bus.py`、`hawkeye.py`、`data_analyst.py`、`attack_tool_master.py`、`blackboard.py`、`context_manager.py`、`server/app.py`

**收益**：不会在已失败的路径上继续执行后续步骤；失败后自动调整策略而非机械完成所有步骤

### P5（远期）：条件步骤 + async 迁移

- PlanStep.conditional 支持
- asyncio 替代 threading
