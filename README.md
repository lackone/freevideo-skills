# freevideo-skills

通过本机 FreeVideo 本地引擎（如 MiniMax H3 Image）HTTP 接口生成图片，返回本地文件。纯 Python 标准库，无需 `pip install`，不含云厂商 API Key，包内不含任何 token 或密钥。

## 能力

| 脚本 | 能力 | 默认参数 |
|---|---|---|
| `scripts/freevideo_image.py` | 本地引擎文生图：鉴权、提交、轮询、下载 | 比例 `16:9`，档位 `standard`（约 4 MP），模型 `minimax-h3-image` |

## 包内文件

```
freevideo-skills/
├── SKILL.md               # 元数据 + 出图指令、提示词规范与交付约定
├── README.md              # 本文件
├── requirements.txt       # 标准库占位，无第三方依赖
├── .gitignore             # 排除密钥、缓存与生成产物
└── scripts/
    └── freevideo_image.py # 生图脚本（纯标准库）
```

## 运行环境

- Python 3.10+，仅用标准库，无需第三方包或虚拟环境；`requirements.txt` 仅作打包/审计占位。
- 本机（或可达内网机器）正在运行 FreeVideo 服务并具备 agent token 文件；隔离沙箱连不上本地服务时只能加载提示词规范，无法出图。

## 安装

把 `freevideo-skills/` 整个目录放入客户端技能目录（`SKILL.md` 在技能根目录）：

- Codex：项目级 `.agents/skills/freevideo-skills/`，或用户级 `~/.agents/skills/freevideo-skills/`。
- 豆包：技能管理 → 添加技能 → 上传本文件夹或 ZIP。
- 其它兼容客户端：放入其技能发现目录（通常 `<project>/.agents/skills/` 或 `~/.agents/skills/`）。

## 配置参数

token 文件与服务地址默认由脚本通过服务发现自动获取：先 `GET {服务地址}/freevideo/agent` 取 JSON，再访问其中 `connect` 地址拿到接入说明，从中解析令牌路径；包内不写死机器特定路径。需要覆盖时用命令行参数：

| 命令行参数 | 作用 | 默认值 |
|---|---|---|
| `--origin` | FreeVideo 服务地址 | `http://127.0.0.1:8188` |
| `--token-path` | 显式指定 token 文件路径（可选覆盖） | 服务发现自动获取 |
| `--output-dir` | 成片保存目录 | 当前工作目录下的 `images/` |

## 运行

```bash
python "scripts/freevideo_image.py" --prompt "<原生提示词 + 润色改写>"
```

可选参数：

- `--origin <地址>`：FreeVideo 服务地址，默认 `http://127.0.0.1:8188`
- `--token-path <路径>`：显式指定 agent token 文件路径
- `--aspect 9:16`（可选 `1:1` / `16:9` / `4:3` / `3:4`，默认 `16:9`）
- `--tier high`（约 16 MP，更慢；默认 `standard`）
- `--model`：可选 `minimax-h3-image`（默认）/ `qwen-image-2.1-turbo`
- `--label <2-8 字>`（任务卡片短名）
- `--output-dir <目录>`（默认当前工作目录下的 `images/`，调用方应传绝对路径）

提示词硬上限 2000 字符（原文+改写合计，按 Python `len()` 计），脚本提交前校验，超限报中文错误。

## 输出与交付

- 成功时 stdout 只打印一行成片本地绝对路径；进度与错误走 stderr。
- 原样返回，不裁切、缩放、调色、修图或转格式；瑕疵由用户自行判断。
- `images/` 下只保留生成的成片，日志、临时文件交付后即删，不随包分发。

## 错误处理

- 网络/超时抖动与 HTTP 5xx 自动重试至多 2 次（间隔 0.8s）；4xx 与鉴权问题不重试。
- 缺/空 token、发现失败、服务不可达、任务失败、900s 超时、下载为空或非图片、写盘失败，均输出一句中文错误并退出码 1；不自行重试生成，仅在用户要求时重新生成。

## 安全

token 只在本机被脚本读取，不打印、不进日志、不随包分发；不要把本机 token 文件内容分享出去。
