# Run ReelCut on your Windows PC (free)

Open **PowerShell as Administrator** (Start menu, type `PowerShell`, right-click, *Run as administrator*) and paste:

```
irm https://raw.githubusercontent.com/Eshwin6/reelcut/main/windows/setup.ps1 | iex
```

It installs Docker Desktop and Tailscale and asks you for an app password. Then it builds ReelCut, starts it with `--restart unless-stopped` and a persistent `reelcut-data` volume, and puts it on Tailscale.

- If Docker was just installed, it asks you to restart the PC. Run the command again afterwards.
- It asks whether to make the app reachable for auto-posting. Instagram and TikTok can only fetch videos and finish logins over a public https link (Tailscale Funnel), and the app stays behind your password. If you answer no, it only opens on your own devices that have Tailscale.
- Your files are kept in `C:\Users\<you>\reelcut`, and the password is in `.env` there.
- To update, run the same command again. Your data is kept.
- Keep the PC on and awake (Settings > System > Power > Sleep: Never).
