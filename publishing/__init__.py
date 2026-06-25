"""Publishing renderers.

A Thelivu article is parsed once into a platform-neutral Article + Blocks
(`publishing.parser`), then each platform renderer serialises it its own way.
Telegram is built today (`publishing.telegram`); Medium/Instagram can be added
as new modules that consume the same Article/Blocks, with no parser changes.
"""
