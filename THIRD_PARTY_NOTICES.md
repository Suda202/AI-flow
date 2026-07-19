# Third-party sources and references

AI Flow consumes public outputs from the projects below. Their repositories are not vendored into this project, and AI Flow does not copy their private data, account systems, paid-source connectors, or generated rewrite bodies.

## Follow Builders

- Project: <https://github.com/zarazhangrui/follow-builders>
- License declared by the upstream README: MIT
- Usage here: public `feed-x.json`, `feed-blogs.json`, and transcript-backed `feed-podcasts.json`. Podcast episodes are deduplicated against YouTube by concrete video URL, so overlapping channels do not create duplicate cards while unique or missed episodes can supplement the digest.

## QMReader

- Project: <https://github.com/joeseesun/qmreader>
- License: MIT, Copyright (c) 2026 向阳乔木
- Usage here: public entry metadata from `https://rss.qiaomu.ai/api/entries`. AI Flow reads titles, summaries, URLs, timestamps, sources, and aggregate stats; it does not use QMReader's generated style-rewrite assets.

## AI News Radar

- Project: <https://github.com/LearnPrompt/ai-news-radar>
- License: MIT, Copyright (c) 2026 LearnPrompt
- Usage here: public event-level `data/daily-brief.json`. AI Flow consumes the normalized brief and its evidence counts without copying the upstream crawler or paid-source pipeline.

These notices describe the integration boundary and do not replace the upstream license texts. Follow each upstream project's current terms when redistributing a substantial portion of its software.
