# Set up YouTube posting

Clipsmith posts clips to **your own** YouTube channel through Google's official YouTube Data API. Because Clipsmith runs on your computer, you create your own free Google "app" once. It takes about 5 minutes and costs nothing.

Nothing secret is shipped with Clipsmith: your keys stay in your `.env` file, and the YouTube login is saved in `data/youtube_token.json` on your computer.

## 1. Create a Google Cloud project

1. Open the [Google Cloud console](https://console.cloud.google.com/) and sign in with the Google account that owns your YouTube channel.
2. Create a new project (any name, e.g. `clipsmith`) and select it.

## 2. Turn on the YouTube Data API

1. Open the [API Library](https://console.cloud.google.com/apis/library).
2. Search for **YouTube Data API v3** and click **Enable**.

## 3. Set up the consent screen

1. Go to **Menu → Google Auth platform → Branding** and fill in an app name (e.g. `Clipsmith`) and your email.
2. Under **Audience**, choose **External**.
3. **Important:** on the **Audience** page, click **Publish app** so the status is **In production**.
   > If you leave it in **Testing**, Google makes your YouTube login expire **every 7 days** and you'd have to reconnect each week.

You don't need Google's app verification: apps for personal use with fewer than 100 users can be used without it.

## 4. Create the OAuth client

1. Go to **Menu → Google Auth platform → Clients** and click **Create Client**.
2. **Application type:** **Desktop app**. Name it anything and click **Create**.
3. Copy the **Client ID** and **Client secret**.

## 5. Add them to Clipsmith

Open the `.env` file in the Clipsmith folder and add:

```
YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your-client-secret
```

Restart Clipsmith (`run.bat` or `./run.sh`).

## 6. Connect your channel

1. Click **Connect YouTube** at the top of the Clipsmith page.
2. Choose your Google account. Google shows **"Google hasn't verified this app"**. That's expected for your own personal app: click **Advanced → Go to Clipsmith (unsafe)**. It's "unsafe" only in the sense that Google hasn't reviewed it; it's your own app.
3. Allow the permissions:
   - **Upload YouTube videos** (`youtube.upload`) to post clips.
   - **View your YouTube account** (`youtube.readonly`) so Clipsmith can show which channel is connected.
4. You're sent back to Clipsmith and the top bar shows your channel name.

## Posting

Click **Post to YouTube** on any clip. The title, description and hashtags are pre-filled from the AI and you can edit them.

- **Post now** or **Schedule**: a scheduled video is uploaded straight away as private, and **YouTube makes it public at the chosen time by itself**. Your computer doesn't need to be on. Scheduled posts are always public; to keep a clip unlisted or private, post it now with that visibility.
- **Made for kids**: YouTube requires an answer for every video.
- **Add the full video link**: puts a link to the original video between the description and the hashtags (only for clips made from a YouTube link).
- Vertical or square videos up to 3 minutes are treated as **Shorts** by YouTube automatically.

## Limits

- Google allows **100 uploads per day** per Google Cloud project.
- Titles: up to 100 characters. Descriptions: up to 5000 bytes. Hashtags/tags: up to 500 characters in total. Clipsmith trims to these automatically.
- `<` and `>` aren't allowed in titles or descriptions; Clipsmith removes them.

## Disconnect

Click **Disconnect** at the top. Clipsmith revokes its access with Google and deletes the saved login. You can also remove access any time at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Troubleshooting

| Message | Fix |
|---|---|
| "YouTube isn't set up yet" | Add `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` to `.env` and restart. |
| Login expires every week | Your app is in **Testing**. Click **Publish app** (step 3) and reconnect. |
| "daily limit of 100 uploads" | Wait until tomorrow (the quota resets daily). |
| `redirect_uri_mismatch` | Make sure the OAuth client type is **Desktop app**, not Web application, and open Clipsmith at `http://127.0.0.1:8765`. |
