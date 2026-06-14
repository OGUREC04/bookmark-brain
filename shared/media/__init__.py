"""Media processing shared between the bot and the backend worker.

- ``stt``        — speech-to-text (Whisper / Yandex SpeechKit).
- ``extractor``  — document text extraction (PDF / DOCX / TXT / MD).

Import submodules directly, mirroring the previous ``bot.services.*`` layout::

    from shared.media.stt import create_stt_service
    from shared.media.extractor import extract_text, detect_format
"""
