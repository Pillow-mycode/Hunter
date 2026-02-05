<p align="center">
  <img src="./hunter-server/photo/hunter.png" alt="hunter" width="300" />
</p>

#                                              Hunter

一款基于 LLM 驱动的可在windows/mac上访问的自动化渗透测试工具，采用多智能体协作架构，可以在Kali环境下充分集成，实现Kali工具的自动化利用。你也可以用它对你自己的网站进行渗透性测试，所以它既可以是你与工具之间的“翻译官”，也可以是你的自动化渗透的“雇佣兵”。

## 为什么需要

Hunter 是一个强大的自动化渗透测试系统。在这里，你不需要记住那些多而杂的工具名或参数，你只需要清楚自己想干什么，将所有经历专注于问题思路和解决方案上。为什么集成在Kali上？因为Kali上有着丰富的”武器库“，只需要加上它，Hunter将不再是一个只会给建议的指挥员，而是真正为你做事的士兵。

---

### 部署说明

本项目主推将服务端部署到Kali上，虽然也支持Windows，但工具方面没有Kali方便。所以最好准备一台Kali主机或虚拟机。Kali虚拟机安装方式参考：[Kali Linux下载安装及配置（VMware虚拟机）保姆级图文教程（持续更新）kali安装2026最新，0基础可用，保姆级图文（2024年11月19日发布，2026/1/1最新更新）_kali虚拟机-CSDN博客](https://blog.csdn.net/m0_74030222/article/details/143866270?ops_request_misc=elastic_search_misc&request_id=1f3cdc30a9a4f5a0e585ab6f06852f7f&biz_id=0&utm_medium=distribute.pc_search_result.none-task-blog-2~all~top_positive~default-1-143866270-null-null.nonlogin&utm_term=kali)

**！！！注意：尽量不要将本项目部署到公网服务器上， 如果有特殊需求需要映射到公网，请做好服务器出入站限制**

---

## 配置服务端（Kali Linux上）

### 环境要求

- Kali Linux（服务端）

- Python 3.8+ （Kali自带）
- 安装常用渗透工具（Kali 预装）

### 1. 安装依赖

```bash
#进入项目
cd hunter-server

#创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

在Hunter/hunter-server目录下创建 `.env` 文件并进入，粘贴并配置以下内容（注意：这里有四部分，可以仅配置第一个默认部分其他为空即可，如需要单独为不不同智能体选择不同模型直接填入信息即可，默认优先级：专门配置 > 默认配置）：

```env
# ==================== 默认配置 ====================
# 当各智能体的专用配置为空时，使用这些默认值
DEFAULT_API_KEY=your-api-key-here
DEFAULT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEFAULT_MODEL=qwen3-max

# ==================== 武器大师配置 ====================
# 负责工具选择和命令执行
ATTACKER_API_KEY=
ATTACKER_BASE_URL=
ATTACKER_MODEL=

# ==================== 鹰眼配置 ====================
# 负责检测终端是否需要用户交互
HAWKEYE_API_KEY=
HAWKEYE_BASE_URL=
HAWKEYE_MODEL=

# ==================== 渗透专家配置 ====================
# 负责任务规划和决策
LEADER_API_KEY=
LEADER_BASE_URL=
LEADER_MODEL=
```

#### 配置说明

- **API Key**：必填，填写你的 LLM 服务商 API Key（如阿里云 DashScope、OpenAI 等）
- **Base URL**：必填，API 服务地址
- **Model**：必填，使用的模型名称

#### 配置优先级

每个智能体的配置都遵循优先级规则：**专用配置 > 默认配置**

示例：
- 如果 `ATTACKER_API_KEY` 有值 → 使用 `ATTACKER_API_KEY`
- 如果 `ATTACKER_API_KEY` 为空 → 使用 `DEFAULT_API_KEY`
- 如果两者都为空 → 报错

#### 推荐配置方案

**方案 1：统一配置（推荐）**
```env
DEFAULT_API_KEY=sk-xxx
DEFAULT_BASE_URL=https://api.example.com/v1
DEFAULT_MODEL=gpt-4

# 其他配置留空，自动使用默认值
ATTACKER_API_KEY=
HAWKEYE_API_KEY=
LEADER_API_KEY=
```

**方案 2：差异化配置**
```env
DEFAULT_API_KEY=sk-xxx

# 武器大师使用更强的模型
ATTACKER_MODEL=qwen3-max-latest

# 鹰眼使用更快的模型（降低成本）
HAWKEYE_MODEL=qwen3-turbo

# 渗透专家使用默认模型
LEADER_API_KEY=
```

### 3. 启动 FastAPI 服务端

```bash
python server/app.py
```

服务启动后：
- API 地址：`http://0.0.0.0:8000`
- WebSocket 地址：`ws://0.0.0.0:8000/ws/{session_id}`



## 访问客户端（Windows/Mac 确保和Kali Linux主机在同一内网下）

#### 方式1（推荐）：直接访问  [Hunter - 自动化渗透测试系统](http://42.193.116.16/)

#### 方式2：将本项目的 ”/hunter-clinet“ 目录直接放到本机上，用浏览器直接打开其中的index.html即可



确定客户端主机与kali在同一内网下后需要拿到kali的IP，用来访问服务端：

![kali](./hunter-server/photo/kali.png)

再将此地址填入客户端即可：

![clientphoto](./hunter-server/photo/clientphoto.png)

完成后即可开始测试！！

---



## 系统架构图

```
┌──────────────────────────────────────────────────────────────┐
│                      Windows 客户端                           │
│                        (Web UI)                              │
│                  - 用户交互界面                              │
│                  - 会话管理                                  │
│                  - 实时进度展示                              │
└──────────────────────────────────────────────────────────────┘
                              │
                    HTTP / WebSocket
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     Kali 服务端                              │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    Web API 层                          │  │
│  │              (FastAPI + WebSocket)                     │  │
│  │         接收请求 / 进度推送 / 用户交互                   │  │
│  │  - POST /session: 创建会话                            │  │
│  │  - GET  /session/{id}: 获取会话状态                    │  │
│  │  - WS   /ws/{session_id}: WebSocket 连接               │  │
│  └────────────────────────────────────────────────────────┘  │
│                              │                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                   任务管理器                            │  │
│  │        会话管理 / 并发控制 / 状态持久化                  │  │
│  │  - SessionManager: 管理会话生命周期                   │  │
│  │  - 并发任务调度                                      │  │
│  │  - WebSocket 消息分发                                │  │
│  └────────────────────────────────────────────────────────┘  │
│                              │                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │               渗透专家 (AttackLeader)                   │  │
│  │                    + LLM 决策                           │  │
│  │  - 任务规划：制定渗透测试策略                         │  │
│  │  - 风险评估：评估操作风险等级                         │  │
│  │  - 用户沟通：用自然语言与用户交流                     │  │
│  └────────────────────────────────────────────────────────┘  │
│                              │                               │
│                         函数调用                             │
│                              │                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              武器大师 (AttackToolMaster)                │  │
│  │  - 工具选择：根据任务选择合适的工具                   │  │
│  │  - 命令生成：生成执行命令                           │  │
│  │  - 结果分析：解析工具输出并提取关键信息               │  │
│  │                                                        │  │
│  │              鹰眼 (Hawkeye) - 交互检测                   │  │
│  │  - 智能判断：检测终端是否需要用户输入                │  │
│  │  - 避免阻塞：及时通知用户输入需求                     │  │
│  └────────────────────────────────────────────────────────┘  │
│                              │                               │
│                    工具调用 (Kali 内置 + 自定义)            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  [KALI] nmap, sqlmap, hydra, nikto, gobuster...   │  │
│  │  [CUSTOM] brute_force_attack.py                      │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 客户端和服务端部署

### 目录结构

```
hunter-server/
├── server/              # 服务端（部署在 Kali Linux）
│   ├── app.py          # FastAPI 服务主程序
│   ├── requirements.txt # 服务端依赖
│   └── __init__.py
│
├── agent/              # 智能体核心模块
│   ├── smart_brain/    # 智能体实现
│   │   ├── attack_leader.py      # 渗透专家
│   │   ├── attack_tool_master.py # 武器大师
│   │   └── hawkeye.py          # 鹰眼
│   ├── pojo/          # 配置类
│   │   ├── leader_config.py     # 渗透专家配置
│   │   ├── attack_config.py      # 武器大师配置
│   │   └── hawkeye_config.py    # 鹰眼配置
│   ├── system/        # 系统模块
│   │   ├── system_command.py     # 命令执行（PTY）
│   │   └── output_handler.py     # 输出处理
│   └── manager/       # 管理器
│       ├── session_manager.py     # 会话管理
│       └── history_manager.py    # 历史记录
│
├── starter/            # 启动入口
│   └── main.py        # CLI 启动入口
│
├── tools/             # 工具库
│   ├── brute_force_attack/  # 暴力破解工具
│   └── tools_readme/       # 工具文档
│
├── logs/              # 日志目录
├── reports/           # 测试报告
├── results/           # 测试结果
├── requirements.txt   # 完整依赖
└── .env              # 环境变量配置（不提交到 Git）
```



## 额外功能

#### 1、本项目还支持自定义渗透工具（要求命令行运行）做法：

将开发的工具包放入上面的目录的tools目录下，然后将工具的名称与简介按 "tool_name:description;" 填入 tools_readme 目录下的 all-tools.txt 中，最后写一个详细的 tool_name.md 文档放入 tools_readme 目录下即可。可以看项目中 brute_force_attack 的例子。

#### 2、关于项目用法：

本项目关键还是主要用于简化命令行工具利用过程，省去记忆的复杂性。做渗透测试如果想要完全的凭借大模型是难以达到的，并且也是不现实的。大模型最主要的作用还是辅助。

---

## 安全提示

⚠️ **本工具仅用于授权的安全测试，请勿用于非法目的**

1. 使用前确保已获得目标系统的书面授权
2. 本工具包含自动化攻击功能，请在合法环境中使用
3. 不要对 .gov、.edu、.mil 等敏感域名进行测试
4. 再次提醒非特殊情况请勿将本项目放在无出入站限制的公网中，否则造成的后果作者均不承担

---

## 许可证

本项目仅供学习和研究使用。

---

## 联系方式

如有问题或建议，欢迎提交 Issue。
