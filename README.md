你好，我是 Ashwin 👋

## 主项目：ShuaDouyin

[ShuaDouyin](https://github.com/9Ashwin/ShuaDouyin) 是一个面向 Agent 的本地抖音 CLI/TUI，让调用方带着人格和记忆浏览公开内容、记录关系，并获得有来源的后续建议。它不自带模型或后台调度，内容判断留给调用方。

- 读取公开主页、作品和评论，观察互动与回复
- 用本地记忆、关系卡片和跟进事项保持上下文
- 对外写操作带请求 ID 和收据；结果不确定时不会自动重发
- 不绕过平台验证；评论、私信等操作有账号与平台风险

```bash
npm install -g shuadouyin
dy guide
```

包名是 `shuadouyin`，命令是 `dy`。也可以从源码装：`npm install -g github:9Ashwin/ShuaDouyin`。

TypeScript · Node.js 22.19+ · MIT · [npm](https://www.npmjs.com/package/shuadouyin)

## 其他项目

[sticker-cli](https://github.com/9Ashwin/sticker-cli) — 面向 Agent 的本地表情包 CLI。
