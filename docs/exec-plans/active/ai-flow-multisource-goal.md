# AI Flow 多源改造目标

## 目标

把现有 YouTube Digest 升级为 AI Flow：在保留 YouTube 长视频、AI HOT、飞书推送和偏好学习的基础上，接入 Follow Builders、AI News Radar 与 QMReader 的公开数据产物。

## 验收标准

- Follow Builders 只接入 X Builder 动态和官方博客，不重复接入播客。
- AI News Radar 只消费公开、带时间戳的事件级 JSON，不复制其抓取器或付费源。
- QMReader 只消费公开文章元数据，不使用第三方风格改写正文。
- 所有信息源归一化为统一字段，保留 canonical URL 和来源类型。
- 跨来源按 canonical URL 去重，失败源不阻塞其他来源或 YouTube。
- 统一复用当前个性化筛选、飞书卡片、去重历史和反馈学习。
- 每日信息动态总量可配置，允许为 0，默认保持少而精。
- 项目展示名、文档、工作流、本地目录和 GitHub 仓库统一为 AI Flow。
- 新增解析、去重、失败降级、卡片反馈测试，完整测试通过。

## 不做

- 不创建 Follow Builders、QMReader 或 AI News Radar 的独立定时任务。
- 不复制三个仓库的 UI、数据库、账号系统或付费社媒适配器。
- 不引入 Telegram、邮件、私有 OPML、cookies 或新密钥。
- 不把第三方完整仓库或运行数据提交进本项目。
