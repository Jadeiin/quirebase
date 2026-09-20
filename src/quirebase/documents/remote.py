from __future__ import annotations

import asyncio
import ipaddress
import socket
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import IO, TYPE_CHECKING
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx2

from quirebase.core.errors import (
    ResourceNotFound,
    SizeLimitExceeded,
    UpstreamServiceError,
    ValidationFailure,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True)
class RemoteAttachment:
    content: AsyncIterator[bytes]
    filename: str
    media_type: str


def _validated_url(source: str) -> str:
    value = source.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationFailure("attachment URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValidationFailure("attachment URL must not contain credentials")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValidationFailure("attachment URL contains an invalid port") from error
    return value


async def _resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise UpstreamServiceError("attachment source address could not be resolved") from error
    return tuple(dict.fromkeys(row[4][0] for row in rows))


async def _public_request_target(source: str) -> tuple[str, str, str]:
    """Resolve and pin one public address while retaining HTTP host and TLS SNI."""
    value = _validated_url(source)
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if hostname is None:
        raise ValidationFailure("attachment URL must include a host")
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValidationFailure("attachment URL contains an invalid host") from error
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        literal = ipaddress.ip_address(ascii_hostname)
    except ValueError:
        addresses = await _resolve_addresses(ascii_hostname, port)
    else:
        addresses = (str(literal),)
    if not addresses:
        raise UpstreamServiceError("attachment source address could not be resolved")

    resolved = tuple(ipaddress.ip_address(address) for address in addresses)
    if any(not address.is_global for address in resolved):
        raise ValidationFailure("attachment URL must resolve only to public addresses")

    chosen = str(resolved[0])
    pinned_host = f"[{chosen}]" if resolved[0].version == 6 else chosen
    pinned_authority = f"{pinned_host}:{port}"
    original_host = f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname
    default_port = 443 if parsed.scheme == "https" else 80
    host_header = original_host if port == default_port else f"{original_host}:{port}"
    request_url = urlunsplit((parsed.scheme, pinned_authority, parsed.path, parsed.query, ""))
    return request_url, host_header, ascii_hostname


def _filename(headers: httpx2.Headers, source: str) -> str:
    message = Message()
    message["content-disposition"] = headers.get("content-disposition", "")
    candidate = message.get_filename() or unquote(urlsplit(source).path.rsplit("/", 1)[-1])
    name = Path(candidate).name[:255]
    return name if name not in {"", ".", ".."} else "attachment"


async def _chunks(stream: IO[bytes]) -> AsyncIterator[bytes]:
    while chunk := await asyncio.to_thread(stream.read, 64 * 1024):
        yield chunk


@asynccontextmanager
async def acquire_remote_attachment(source: str, max_bytes: int) -> AsyncIterator[RemoteAttachment]:
    """Download an arbitrary attachment with bounded transport and storage."""
    current_url = _validated_url(source)
    with tempfile.SpooledTemporaryFile(max_size=5_000_000, mode="w+b") as stream:
        try:
            for _redirect in range(6):
                request_url, host_header, sni_hostname = await _public_request_target(current_url)
                # A fresh pool prevents a connection pinned for one redirect host
                # from being reused for another host that resolved to the same IP.
                async with (
                    httpx2.AsyncClient(
                        timeout=15.0, follow_redirects=False, trust_env=False
                    ) as client,
                    client.stream(
                        "GET",
                        request_url,
                        headers={"Host": host_header},
                        extensions={"sni_hostname": sni_hostname},
                    ) as response,
                ):
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            raise UpstreamServiceError(
                                "attachment source returned an invalid redirect"
                            )
                        current_url = _validated_url(urljoin(current_url, location))
                        continue
                    if response.status_code == 404:
                        raise ResourceNotFound("attachment source was not found")
                    if response.status_code >= 400:
                        raise UpstreamServiceError("attachment source request failed")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        raise SizeLimitExceeded("attachment exceeded the size limit")
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise SizeLimitExceeded("attachment exceeded the size limit")
                        await asyncio.to_thread(stream.write, chunk)
                    await asyncio.to_thread(stream.seek, 0)
                    media_type = response.headers.get("content-type", "").split(";", 1)[0]
                    yield RemoteAttachment(
                        content=_chunks(stream),
                        filename=_filename(response.headers, current_url),
                        media_type=media_type or "application/octet-stream",
                    )
                    return
            raise UpstreamServiceError("attachment source returned too many redirects")
        except httpx2.HTTPError as error:
            raise UpstreamServiceError("attachment source request failed") from error
