---
title: ReelCut
emoji: 🎬
colorFrom: pink
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# ReelCut

Drop raw footage in from your phone. ReelCut edits it into a Reel/TikTok and posts it. Everything is free.

**What it does to every upload**
- Joins all the clips you selected and crops them to 9:16.
- Removes bad takes. When you repeat a line, it keeps the last attempt. It also removes "um/uh".
- Cuts out dead air: every pause longer than 0.3 s.
- Adds a small zoom on every other cut so jump cuts look smooth.
- Adds word-by-word captions: bold caps, with the spoken word on a pink box.
- Adds a hook headline with emoji for the first 3 seconds.
- Writes the post caption and hashtags. You can also type your own hook or caption.
- Adds background music from your library if you want it. The music dips while you talk.
- Posts to Instagram and TikTok automatically.

## 1. Put it online for free (Hugging Face)

Do this once, on a computer or your phone.

1. Make a free account at **huggingface.co**.
2. Go to **huggingface.co/new-space**.
   - Name it `reelcut`.
   - For **SDK**, pick **Docker** and then the **Blank** template.
   - For hardware, keep **CPU basic (free)**.
   - Visibility: **Public**. Instagram has to be able to fetch finished videos, and the app is protected by your password.
3. Add the code. The easiest way, which works on a phone: in the Space go to **Files → Add file → Create new file** and create two files, `Dockerfile` and `README.md`. Copy their contents from the `hf-space/` folder of the GitHub repo, and in the Dockerfile it already points at github.com/Eshwin6/reelcut. The Space downloads the rest of the code by itself.
   (On a computer you can instead upload every file in this folder with **Files → Add file → Upload files**.)
4. Make a token: click your profile → **Settings → Access Tokens → Create new token**, choose type **Write**, and copy it.
5. In the Space, go to **Settings → Variables and secrets** and add these secrets:
   - `APP_PASSWORD`: any password you like.
   - `HF_TOKEN`: the token from step 4. This keeps your brands, music and connected accounts saved.
6. Wait for it to say **Running**. The first build takes about 10 minutes.
7. Your app is at `https://<your-username>-reelcut.hf.space`.

## 2. Put it on your phone

Open that address in Safari (iPhone) or Chrome (Android). Tap **Share → Add to Home Screen**, then log in with your password.

## 3. Connect Instagram (free)

1. The Instagram account must be a **Creator** or **Business** account. You can switch in the Instagram app under Settings → Account type.
2. On **developers.facebook.com**, create an app with the type **Business**. Add the product **Instagram** and choose **"API setup with Instagram login"**.
3. Under **Business login settings**, set the redirect URL to:
   `https://<your-username>-reelcut.hf.space/auth/instagram/callback`
4. Copy the **Instagram app ID** and **Instagram app secret** into the Space secrets `IG_APP_ID` and `IG_APP_SECRET`.
5. Under **Roles**, add your Instagram account as a tester and accept the invite in Instagram.
6. In ReelCut, scroll down to **Accounts** and tap **Connect Instagram**.

## 4. Connect TikTok (free)

1. On **developers.tiktok.com**, create an app. Add **Login Kit** and the **Content Posting API**, and turn on **Direct Post**.
2. Set the redirect URI to:
   `https://<your-username>-reelcut.hf.space/auth/tiktok/callback`
3. Copy the **Client key** and **Client secret** into the Space secrets `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET`.
4. In ReelCut, tap **Connect TikTok**.
5. Until TikTok reviews your app, posts go up **private** (only you can see them). Open the post in TikTok and switch it to public. To get public posting, submit the app for review in the TikTok developer portal. When it's approved, add the secret `TIKTOK_PRIVACY` = `PUBLIC_TO_EVERYONE`.

The app renews both logins automatically. Until an account is connected, use the **Share** button on a finished video. It opens Instagram or TikTok with the video ready and the caption copied.

## Using it

1. Tap **Upload footage** and pick your clips.
2. If you want, choose a brand, the type of video and music, or type your own hook or caption.
3. Turn on **Auto-post when ready** to have it post by itself.

The app remembers your choices. Videos are processed one at a time. On the free server a 1-minute video takes roughly 3–5 minutes, so 30 a day works if you upload through the day.

## Brands and music

- **Brands tab:** each company's hashtags (always added), a line about the product, and a call to action written as `CTA: Download Juno free in the App Store`.
- **Music tab:** add royalty-free songs and give each a mood (upbeat, chill, motivational, emotional). "Pick for me" chooses a song whose mood fits the video type.

## Later: turning on the AI (paid)

The free version writes hooks and captions from what you said, using templates for each video type. For smarter bad-take removal and better hooks and captions, add the secret `ANTHROPIC_API_KEY` (from console.anthropic.com). Nothing else changes.

## Good to know about the free server

- It sleeps after about 2 days without use. Opening the app wakes it in a minute or two.
- Finished videos are deleted after 3 days. Brands, music and accounts are kept.
- If 30 a day turns out too slow, upgrading the Space hardware is the next step. That's a paid option.
