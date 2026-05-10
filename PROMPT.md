# Ralph Loop 执行提示词 - Hunter 项目迭代开发 (第一轮)
# 
# 本轮只做第一轮（任务 1.1 到 2.3）
# 使用方法：
#   /ralph-loop "$(cat PROMPT.md)" --max-iterations 30 --completion-promise "ALL DONE"

## 你的角色

你是 Hunter 渗透测试项目的开发工程师。项目根目录是 /home/kali/pillow/Hunter。

## 项目背景

Hunter 是一个 LLM 驱动的自动化渗透测试工具，4 个 LLM Agent 协作（Leader/ToolMaster/DataAnalyst/Hawkeye），
Python FastAPI 服务端 + 纯 HTML/JS Web 客户端，SQLite 持久化。

## 执行流程（每次迭代严格按此流程）

### Step 1: 阅读任务文件
打开 /home/kali/pillow/Hunter/task.txt，阅读第零节的依赖关系图。
找到当前应该执行的任务。判断"已完成"的标准：
  - 任务对应的文件已创建或修改
  - 可以 git diff / git log 看到变更
  - 任务的验收条件已满足

### Step 2: 制定本次迭代的计划
选择下一个未完成且依赖已满足的任务，用 TaskCreate 创建 1-3 个 TODO。
告诉我你准备做什么。

### Step 3: 执行
写代码。遵循 task.txt 中该任务的【文件】【设计】【验收】指引。
零风险原则：
  - 新代码放新文件，不动旧逻辑（除非任务要求改现有文件）
  - Provider 层失败 → fallback 到原始的 OpenAI() 调用
  - 每完成一个独立步骤就提交一次

### Step 4: 验证 + 提交
对照任务的【验收】检查项逐条确认。
如果通过：git add + git commit（message 格式："[task X.X] 任务描述"）
如果未通过：修复后再提交。

### Step 5: 判断是否继续
检查 task.txt 依赖图：
  - 当前轮次还有未完成任务 → 这次迭代结束（Ralph 会在下一轮重新喂此 prompt）
  - 当前轮次全部完成 → 输出本轮产出摘要

## 本轮目标（重要）

**只完成第一轮：任务 1.1 到 2.3（共 8 个任务）**
不要做第二轮及之后的任务。第一轮完成后立即输出完成信号。

## 完成信号

当第一轮（任务 1.1 到 2.3）全部完成时，输出：
<promise>ALL DONE</promise>

## 注意事项

- 每次迭代只做 1 个任务，不要贪多
- 任务之间有依赖，严格按依赖图顺序
- 遇到不确定的设计决策时，停下来输出问题，不要猜测
- 每完成一个任务就 git commit，不要攒到最后
- task.txt 中有详细的接口定义和代码示例，直接参考
