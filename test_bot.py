from datetime import datetime, timezone

from bot import chunks, parse_feed

NOW = datetime(2026, 11, 10, 3, 30, tzinfo=timezone.utc)
RSS = b"""<rss><channel>
<item><title>Fresh</title><link>https://a</link><description>&lt;p&gt;Hi &amp;amp; bye&lt;/p&gt;</description>
<pubDate>Tue, 10 Nov 2026 01:00:00 GMT</pubDate></item>
<item><title>Old</title><link>https://b</link><pubDate>Sat, 07 Nov 2026 01:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title>
<link href="https://c"/><updated>2026-11-09T20:00:00Z</updated></entry></feed>"""

assert parse_feed(RSS, NOW) == [("Fresh", "https://a", "Hi & bye")]
assert parse_feed(ATOM, NOW) == [("A", "https://c", "")]

parts = chunks("a" * 1000 + "\n\n" + "b" * 1000 + "\n\n" + "c" * 4000)
assert all(len(p) <= 1500 for p in parts) and "".join(parts).replace("\n", "") == "a" * 1000 + "b" * 1000 + "c" * 4000
print("ok")
