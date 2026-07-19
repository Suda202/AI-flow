# AI Flow 多源改造进度

## 基线

- 当前分支：`codex/ai-flow-multisource`
- 基线测试：`python3 -m unittest discover -s tests -q`，37 个测试通过。
- 参考仓库已浅克隆到 `/private/tmp/ai-flow-references-20260719/`，不会提交。
- Follow Builders Skill 源码位于 `~/.agents/skills/follow-builders`。

## 来源判断

- Follow Builders：公开 GitHub JSON；接入 X、博客和带逐字稿播客，按具体节目 URL 与 YouTube 去重。
- AI News Radar：公开 GitHub JSON；接入 `daily-brief.json`，跳过复制抓取管线。
- QMReader：公开 `/api/entries`；只用原始标题、中文标题、摘要、URL、发布时间和来源 ID。

## 已完成

- [x] 新增 `information_sources.py`，统一解析、时间窗校验、canonical URL、跨源去重和故障隔离。
- [x] 接入现有质量筛选、偏好提示、中文本地化、飞书卡片、历史去重和反馈学习。
- [x] 更新 GitHub Actions 的多源开关与候选数量配置。
- [x] 更新 README、第三方来源/许可证边界和 AI Flow 品牌。
- [x] 增加解析、脏字段、ID 冲突、候选上限、去重、故障隔离、反馈和工作流测试。
- [x] 增加最多 7 条总预算、最多 3 条深度视频、来源/作者/探索位多样性约束。
- [x] 校准不同上游分数，并让反馈学习区分播客访谈、官方博客、Builder 短观点、多源事件和文章。
- [x] 改为仅永久去重实际推送内容，未入选候选保留后续竞争资格。

## 验证

- `python3 -m unittest discover -s tests -q`：62 个测试通过。
- Python 编译检查：`main.py`、`information_sources.py`、`preference_learning.py`、`update_preferences.py` 通过。
- JavaScript 语法检查：Cloudflare Worker 与 Vercel handler 通过。
- `git diff --check`：通过。
- 线上只读探测（72 小时、每源最多 20 条）：AI News Radar 17 条、Follow Builders 20 条、QMReader 20 条；跨源 URL 去重后 52 条，必填字段完整。
- 播客线上验证：成功读取 `Unsupervised Learning` 节目、YouTube 视频 ID 和 49,013 字符逐字稿；节目级去重字段完整。
- 真实候选兜底排序演练：排除周刊、安装指南、纯运行时细节、垂直房产新闻和仅互动数字内容；近似标题事件合并后宁缺毋滥返回 6 条，并保留 1 条播客。
- 覆盖率：`information_sources.py` 84%、`preference_learning.py` 89%、`update_preferences.py` 82%；新增筛选与卡片行为均有单元/集成测试。旧 `main.py` 仍包含大量网络编排路径，整体项目覆盖率 61%，作为后续拆分债务记录。

## 发布

- [x] 功能提交：`6d74a3f feat: evolve digest into AI Flow`。
- [x] 分支 `codex/ai-flow-multisource` 已推送。
- [x] GitHub 仓库已改名为 `Suda202/AI-flow`，本地 `origin` 已同步。
- [x] 本地迁移目标 `/Users/suda/project/coding/AI-flow` 已确认无冲突；目录改名安排为发布后的最后一步。
