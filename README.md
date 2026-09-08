# Publora for Open WebUI

A tool that publishes what you write in Open WebUI to LinkedIn, X, Instagram,
Threads, TikTok, YouTube, Facebook, Bluesky, Mastodon and Telegram through
[Publora](https://publora.com). Attach a file to the chat and it goes out with
the post.

## What it does

| Tool | What it does |
|---|---|
| `list_accounts` | Lists your connected accounts with the id needed to post to each one |
| `publish_post` | Publishes now |
| `schedule_post` | Puts the post in the Publora queue, N hours ahead |
| `create_draft` | Saves a draft, nothing goes out |
| `list_posts` | Shows recent published, scheduled, draft or failed posts |

## Setup

1. Import the tool, or paste `publora_tool.py` into Workspace, Tools, New Tool.
2. Open the tool settings and paste your Publora API key from
   `app.publora.com`, Settings, API keys. Open WebUI stores it encrypted.
3. Connect at least one social account inside Publora. The tool publishes
   through connections you already made, it does not create them.

Then ask the model to post. It will call `list_accounts` first to learn which
accounts exist, so you can say "post this to LinkedIn" rather than pasting ids.

## Where your data goes

The tool talks to one host, `api.publora.com`, over HTTPS, with your API key in
the `x-publora-key` header. It sends the post text, the account id you chose and,
if you attached a file, the file itself. Nothing else leaves your instance, and
nothing is sent anywhere when the tool is idle.

Publora's [terms](https://publora.com/terms) and
[privacy policy](https://publora.com/privacy) cover what happens to a post after
that. Publora is a paid service with a free tier: 15 posts a month and three
accounts, no card required.

## Attachments

Attach an image or video to the chat message and the tool uploads it to the
post. It uses Publora's own upload flow: create the post, get a signed URL, put
the bytes, confirm. Instagram, TikTok and YouTube require media, so those three
need either an attachment or a public link in `media_url`.

Attaching media to an already scheduled post returns it to draft on Publora's
side, so the tool attaches first and sets the time last. That order is the
reason a scheduled post with a file still goes out on time.

## Requirements

Open WebUI with `httpx` available, which ships with it. A Publora account.

MIT licensed. Issues and pull requests welcome.
