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
- L0: 返回码检测
- L1: 已知错误模式匹配
- L2: 轻量 LLM 判断
- 触发 REPLANNING 状态

**收益**：不会在已失败的路径上继续执行后续步骤

### P5（远期）：条件步骤 + async 迁移

- PlanStep.conditional 支持
- asyncio 替代 threading
