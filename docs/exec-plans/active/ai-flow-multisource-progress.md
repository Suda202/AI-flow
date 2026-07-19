# AI Flow 多源改造进度

## 基线

- 当前分支：`codex/ai-flow-multisource`
- 基线测试：`python3 -m unittest discover -s tests -q`，37 个测试通过。
- 参考仓库已浅克隆到 `/private/tmp/ai-flow-references-20260719/`，不会提交。
- Follow Builders Skill 源码位于 `~/.agents/skills/follow-builders`。

## 来源判断

- Follow Builders：公开 GitHub JSON；接入 X 和博客，跳过与现有频道高度重叠的播客。
- AI News Radar：公开 GitHub JSON；接入 `daily-brief.json`，跳过复制抓取管线。
- QMReader：公开 `/api/entries`；只用原始标题、中文标题、摘要、URL、发布时间和来源 ID。

## 已完成

- [x] 新增 `information_sources.py`，统一解析、时间窗校验、canonical URL、跨源去重和故障隔离。
- [x] 接入现有质量筛选、偏好提示、中文本地化、飞书卡片、历史去重和反馈学习。
- [x] 更新 GitHub Actions 的多源开关与候选数量配置。
- [x] 更新 README、第三方来源/许可证边界和 AI Flow 品牌。
- [x] 增加解析、脏字段、ID 冲突、候选上限、去重、故障隔离、反馈和工作流测试。

## 验证

- `python3 -m unittest discover -s tests -q`：49 个测试通过。
- Python 编译检查：`main.py`、`information_sources.py`、`preference_learning.py`、`update_preferences.py` 通过。
- JavaScript 语法检查：Cloudflare Worker 与 Vercel handler 通过。
- `git diff --check`：通过。
- 线上只读探测（72 小时、每源最多 20 条）：AI News Radar 17 条、Follow Builders 20 条、QMReader 20 条；跨源 URL 去重后 52 条，必填字段完整。

## 待完成

- [ ] 提交并推送分支。
- [ ] GitHub 仓库改名为 `AI-flow`。
- [ ] 本地目录迁移为 `/Users/suda/project/coding/AI-flow`。
