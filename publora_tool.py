"""
title: Publora
author: Publora
author_url: https://publora.com
git_url: https://github.com/publora-team/openwebui-publora
version: 1.0.0
license: MIT
requirements: httpx
description: Publish, schedule and draft social posts on ten networks through Publora. A file attached to the chat goes out with the post.
"""

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import httpx
from pydantic import BaseModel, Field

API = "https://api.publora.com/api/v1"
TIMEOUT = 60


class Tools:
    class Valves(BaseModel):
        api_key: str = Field(
            "",
            description="Publora API key from app.publora.com, Settings, API keys. Stored encrypted.",
        )

    def __init__(self):
        self.valves = self.Valves()
        # Native (Agentic) Mode — единственный поддерживаемый режим вызова,
        # поэтому событий из legacy-набора здесь нет.
        self.citation = False

    # --- разговор с Publora ------------------------------------------------

    async def _call(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        if not self.valves.api_key:
            return {"error": "No API key. Open the tool settings and paste your Publora API key."}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.request(
                    method,
                    f"{API}{path}",
                    headers={"x-publora-key": self.valves.api_key},
                    json=payload,
                )
        except httpx.HTTPError as error:
            return {"error": f"Could not reach Publora: {error}"}

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error:
            return {
                "error": body.get("error")
                or body.get("message")
                or f"Publora responded {response.status_code}"
            }
        return body

    async def _say(self, emitter: Optional[Callable], text: str, done: bool = False) -> None:
        """Строка состояния в интерфейсе: тип status работает в обоих режимах вызова."""
        if not emitter:
            return
        await emitter({"type": "status", "data": {"description": text, "done": done}})

    # --- файлы, прикреплённые в чате ---------------------------------------

    def _first_file(self, files: Optional[list]) -> Optional[dict]:
        """Из вложений берём первое изображение или видео."""
        for entry in files or []:
            item = entry.get("file", entry) if isinstance(entry, dict) else {}
            meta = item.get("meta") or {}
            content_type = meta.get("content_type") or item.get("content_type") or ""
            if content_type.startswith(("image/", "video/")):
                return {
                    "id": item.get("id"),
                    "name": meta.get("name") or item.get("filename") or "upload",
                    "content_type": content_type,
                    "path": item.get("path") or meta.get("path"),
                }
        return None

    def _read_file(self, handle: dict) -> Optional[bytes]:
        """
        Байты вложения. Сначала путь на диске, затем хранилище Open WebUI:
        в разных сборках доступно разное, поэтому пробуем оба пути.
        """
        path = handle.get("path")
        if path:
            try:
                with open(path, "rb") as stream:
                    return stream.read()
            except OSError:
                pass
        try:
            from open_webui.models.files import Files  # type: ignore
            from open_webui.storage.provider import Storage  # type: ignore

            record = Files.get_file_by_id(handle["id"])
            if record and record.path:
                data = Storage.get_file(record.path)
                if isinstance(data, bytes):
                    return data
                with open(data, "rb") as stream:
                    return stream.read()
        except Exception:
            return None
        return None

    async def _attach(self, post_group_id: str, handle: dict) -> Optional[str]:
        """Кладём файл в пост: адрес для заливки, сама заливка, проверка."""
        blob = self._read_file(handle)
        if not blob:
            return "The attached file could not be read on this server."

        slot = await self._call(
            "POST",
            "/get-upload-url",
            {
                "fileName": handle["name"],
                "contentType": handle["content_type"],
                "postGroupId": post_group_id,
            },
        )
        if "error" in slot:
            return f"Publora refused the upload: {slot['error']}"

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                put = await client.put(
                    slot["uploadUrl"],
                    content=blob,
                    headers={"Content-Type": handle["content_type"]},
                )
            if put.is_error:
                return f"The file could not be uploaded ({put.status_code})."
        except httpx.HTTPError as error:
            return f"The file could not be uploaded: {error}"

        await self._call("POST", f"/complete-media/{slot['mediaId']}", None)
        return None

    async def _post(
        self,
        text: str,
        account_id: str,
        when: Optional[str],
        media_url: str,
        files: Optional[list],
        emitter: Optional[Callable],
    ) -> str:
        text = (text or "").strip()
        if not text:
            return "The post text is empty."
        if not account_id:
            return "Pass an account id. Call list_accounts first to see them."

        handle = self._first_file(files)

        # С вложением порядок обязателен: сначала черновик, потом файл, потом
        # время. Прикрепление медиа сбрасывает запланированный пост обратно в
        # черновик, поэтому расписание ставится последним.
        payload: dict = {"content": text, "platforms": [account_id]}
        if media_url and not handle:
            payload["mediaUrls"] = [media_url]
        if when and not handle:
            payload["scheduledTime"] = when

        await self._say(emitter, "Creating the post in Publora")
        body = await self._call("POST", "/create-post", payload)
        if "error" in body:
            return f"Publora refused the post: {body['error']}"

        post_id = body.get("postGroupId", "")
        if handle:
            if not post_id:
                return "Publora did not return a post id, so the file could not be attached."
            await self._say(emitter, f"Uploading {handle['name']}")
            failure = await self._attach(post_id, handle)
            if failure:
                return failure
            if when:
                await self._say(emitter, "Scheduling the post")
                update = await self._call(
                    "PUT",
                    f"/update-post/{post_id}",
                    {"status": "scheduled", "scheduledTime": when},
                )
                if "error" in update:
                    return (
                        f"The file went up but scheduling failed: {update['error']}. "
                        "The post is saved as a draft in Publora."
                    )

        await self._say(emitter, "Done", done=True)
        tail = f" Post id {post_id}." if post_id else ""
        if not when:
            return f"Draft saved for {account_id}.{tail}"
        return f"Queued for {when} on {account_id}.{tail}"

    # --- инструменты -------------------------------------------------------

    async def list_accounts(self, __event_emitter__: Optional[Callable] = None) -> str:
        """
        Lists the social accounts connected to Publora with the id needed to post to each one.
        Call this before publishing so you pass a real account id.
        """
        await self._say(__event_emitter__, "Reading connected accounts")
        body = await self._call("GET", "/platform-connections")
        if "error" in body:
            return body["error"]

        rows = body.get("connections", [])
        if not rows:
            return "No accounts connected yet. Connect one at app.publora.com first."

        lines = [
            f"{item.get('platformId')} — {item.get('displayName') or item.get('username') or 'unnamed'}"
            for item in rows
        ]
        await self._say(__event_emitter__, "Done", done=True)
        return "Connected accounts:\n" + "\n".join(lines)

    async def publish_post(
        self,
        text: str,
        account_id: str,
        media_url: str = "",
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Publishes a post right now to one connected account. A file attached to the chat is sent with it.
        :param text: The text of the post.
        :param account_id: Account id from list_accounts, for example linkedin-ab12cd.
        :param media_url: Optional public link to an image or video, used when no file is attached.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self._post(text, account_id, stamp, media_url, __files__, __event_emitter__)
        if result.startswith("Queued for"):
            return f"Published to {account_id}." + result.split(account_id + ".", 1)[-1]
        return result

    async def schedule_post(
        self,
        text: str,
        account_id: str,
        in_hours: int = 1,
        media_url: str = "",
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Adds a post to the Publora queue and publishes it later. A file attached to the chat is sent with it.
        :param text: The text of the post.
        :param account_id: Account id from list_accounts.
        :param in_hours: How many hours to wait before publishing.
        :param media_url: Optional public link to an image or video, used when no file is attached.
        """
        if in_hours < 1:
            return "Pick at least one hour ahead, or use publish_post to post now."
        when = (datetime.now(timezone.utc) + timedelta(hours=in_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return await self._post(text, account_id, when, media_url, __files__, __event_emitter__)

    async def create_draft(
        self,
        text: str,
        account_id: str,
        media_url: str = "",
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Saves a post as a draft in Publora without publishing it. A file attached to the chat is sent with it.
        :param text: The text of the post.
        :param account_id: Account id from list_accounts.
        :param media_url: Optional public link to an image or video, used when no file is attached.
        """
        return await self._post(text, account_id, None, media_url, __files__, __event_emitter__)

    async def list_posts(
        self,
        status: str = "published",
        limit: int = 10,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Lists recent posts from Publora.
        :param status: One of published, scheduled, draft, failed.
        :param limit: How many posts to return, at most 50.
        """
        if status not in {"published", "scheduled", "draft", "failed"}:
            return "Status must be published, scheduled, draft or failed."
        limit = max(1, min(limit, 50))

        await self._say(__event_emitter__, f"Reading {status} posts")
        body = await self._call("GET", f"/list-posts?status={status}&limit={limit}")
        if "error" in body:
            return body["error"]

        rows = body.get("posts", [])
        if not rows:
            return f"No {status} posts."

        lines = []
        for post in rows:
            networks = ", ".join(t.get("platform", "") for t in (post.get("platforms") or []))
            when = post.get("scheduledTime") or post.get("createdAt") or ""
            body_text = " ".join((post.get("content") or "").split())[:80]
            lines.append(f"{when} [{networks}] {body_text}")

        total = (body.get("pagination") or {}).get("totalItems", len(rows))
        await self._say(__event_emitter__, "Done", done=True)
        return f"{status.capitalize()} posts ({len(rows)} of {total}):\n" + "\n".join(lines)
