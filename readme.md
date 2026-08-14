<h1 align="center" id="title">R4K clipping automation</h1>

##

<p id="description">R4K Auto is an advanced clipping × automation tool designed to transform long-form content into ready-to-post short videos with minimal effort. It automatically selects a random video from a randomly chosen YouTube channel Instagram account or TikTok profile from your provided sources extracts the best moments and converts them into engaging Shorts Reels and TikTok videos with intelligent formatting and automated captions. The tool can enhance every clip by adding background music from your curated Spotify or YouTube playlists while AI-generated titles captions descriptions and hashtags are created specifically for each platform. Once the video is finished R4K Auto completes the workflow by automatically uploading it to YouTube Shorts TikTok and Instagram Reels making the entire process—from content discovery to publishing—fully automated fast and effortless.</p>

<h2>✒️ key features: </h2>
<p> 
🎬 Randomly selects videos from YouTube, Instagram & TikTok.
<br>
✂️ Automatically creates Shorts, Reels & TikToks.
<br>
📱 Formats videos for each platform.
<br>
📝 Generates titles, captions, descriptions & hashtags. <br>
🎵 Adds music from Spotify or YouTube playlists. <br> 
🤖 Automates the entire workflow. <br>
🚀 Automatically uploads to YouTube, Instagram & TikTok. <br> 
⚡ Clip → Edit → Caption → Upload.</p>

<h1 align="center" id="title">📷📸 </h1>

<img src="https://kommodo.ai/i/wW6UcCA8QA6SaAbtMqKX" alt="project-screenshot">



<img src="https://cdn.discordapp.com/attachments/1524520665217237034/1536057633897971833/wm4fxfh.png?ex=6a7aad66&amp;is=6a795be6&amp;hm=6b51fad432c3de2d5efa1684e38514ed6f166a95f970caecef0ac3c72af875e7&amp;" alt="project-screenshot">


## 🤖 SETUP: 

<h4> 1. Download or clone the repo <br> 2. cd to the tool directory 3. open cmd and run: </h4>

```text
python run.py
```

## ⚙️ Project structure:
```text
r4k/
|-- .env
|-- .env.example
|-- .gitignore
|-- config.js
|-- env_editor.pyw
|-- logger.js
|-- machine.js
|-- package.json
|-- package-lock.json
|-- run.js
|-- run.py
|
|-- autodownload/
|   `-- yt-dlp.exe
|
|-- control_panel/
|   |-- __init__.py
|   |-- app.py
|   |-- config.py
|   |-- first_run.py
|   |-- fonts.py
|   |-- logbus.py
|   |-- main.py
|   |-- repair.py
|   |-- splash.py
|   |-- tabs.py
|   |-- test_app.py
|   |-- widgets.py
|   `-- workers.py
|
|-- instagram_uploader/
|   |-- caption.js
|   |-- config.js
|   |-- errors.js
|   |-- logger.js
|   |-- main.js
|   |-- session.js
|   `-- uploader.js
|
|-- queue/
|   |-- insta/
|   |   |-- done/
|   |   `-- upload/
|   |-- tiktok/
|   |   |-- done/
|   |   `-- upload/
|   `-- yt/
|       |-- done/
|       `-- upload/
|
|-- src/
|   |-- account-manager.js
|   |-- ai-provider.js
|   |-- author.png
|   |-- auto-video-pipeline.js
|   |-- background-music.js
|   |-- config.js
|   |-- fs-utils.js
|   |-- Relidux.otf
|   |-- vertical-renderer.js
|   |-- video-cut.js
|   `-- yt-dlp.js
|
|-- state/
|
|-- tiktok_uploader/
|   |-- config.js
|   |-- errors.js
|   |-- logger.js
|   |-- main.js
|   |-- session.js
|   `-- uploader.js
|
|-- user-assets/
|   `-- caption.png
|
|-- work/
|
`-- yt_uploader/
    |-- __init__.py
    |-- config.py
    |-- hashtags.py
    |-- logger.py
    |-- oauth.py
    |-- requirements.txt
    |-- setup_oauth.py
    |-- upload.py
    |-- uploader.py
    `-- youtube_token.json
```
