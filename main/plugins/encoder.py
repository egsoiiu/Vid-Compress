import asyncio
import os
import shutil
import time
from datetime import datetime as dt

from telethon.tl.types import DocumentAttributeVideo
from ethon.telefunc import fast_download, fast_upload
from ethon.pyfunc import video_metadata
from LOCAL.localisation import SUPPORT_LINK
from LOCAL.utils import ffmpeg_progress
from .. import BOT_UN  # only needed if you want username elsewhere


async def encode(event, msg, scale=0):
    """
    Encode video to a given scale (240, 360, 480, 720)
    Preserves thumbnail and original caption
    Reduces FPS only if >30
    Cleans up all temp files/directories
    """
    Drone = event.client
    timestamp = int(time.time())
    temp_dir = f"encodemedia_{timestamp}"
    os.makedirs(temp_dir, exist_ok=True)
    temp_files = []

    edit = await Drone.send_message(event.chat_id, "Trying to process.", reply_to=msg.id)

    try:
        # Determine input file
        file = getattr(msg.media, "document", msg.media)
        mime = getattr(msg.file, "mime_type", "video/mp4")
        original_caption = msg.text or msg.message or ""

        # Determine filename & extension safely
        original_name = getattr(msg.file, "name", "")
        ext = os.path.splitext(original_name)[1] if original_name else ".mp4"
        # Sanitize filename
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"input_{timestamp}{ext}")
        input_file = os.path.join(temp_dir, safe_name)
        temp_files.append(input_file)

        # Download media
        await fast_download(input_file, file, Drone, edit, time.time(), "**DOWNLOADING:**")

        # Standardized filename
        name = os.path.join(temp_dir, f"video_{timestamp}.mp4")
        os.rename(input_file, name)
        temp_files.append(name)

        # Store original file size
        original_size = os.path.getsize(name)

        # Extract metadata
        await edit.edit("Extracting metadata...")
        vid = video_metadata(name)
        if not vid:
            raise ValueError("Failed to extract video metadata.")

        width = int(vid['width'])
        height = int(vid['height'])
        duration = vid['duration']
        original_fps = float(vid.get("fps", 30))

        # Check if video already at requested resolution
        if scale and ((scale == height) or
                      (scale == 240 and width == 426) or
                      (scale == 360 and width == 640) or
                      (scale == 480 and width == 854) or
                      (scale == 720 and width == 1280)):
            await clean_temp_files(temp_files, temp_dir)
            return await edit.edit(f"The video is already in {scale}p resolution.")

        # Determine output resolution
        scale_map = {240: "426x240", 360: "640x360", 480: "854x480", 720: "1280x720"}
        scale_cmd = scale_map.get(scale, f"{width}x{height}")  # fallback to original

        # FPS only if original >30
        fps_cmd = ["-r", "30"] if original_fps > 30 else []

        # Output and progress files
        output_file = os.path.join(temp_dir, f"output_{timestamp}.mp4")
        progress_file = os.path.join(temp_dir, f"progress-{timestamp}.txt")
        temp_files.extend([output_file, progress_file])

        # Build FFmpeg command safely
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-progress", progress_file,
            "-i", name
        ] + fps_cmd + [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "faster",
            "-s", scale_cmd,
            "-crf", "24", "-c:a", "libopus", "-ac", "2", "-ab", "128k",
            "-c:s", "copy", output_file, "-y"
        ]

        # Run encoding with progress
        await ffmpeg_progress(cmd, name, progress_file, time.time(), edit, '**ENCODING:**')

        # Prepare thumbnail if exists
        thumb_path = None
        thumb = None
        if getattr(msg, "video", None) and msg.video.thumbs:
            thumb = msg.video.thumbs[-1]
        elif hasattr(msg.media, 'document') and msg.media.document.thumbs:
            thumb = msg.media.document.thumbs[-1]

        if thumb:
            try:
                thumb_path = os.path.join(temp_dir, f"thumb_{timestamp}.jpg")
                thumb_path = await Drone.download_media(thumb, file=thumb_path)
                temp_files.append(thumb_path)
            except Exception:
                thumb_path = None

        # Video attributes for Telegram
        metadata = video_metadata(output_file)
        width = metadata["width"]
        height = metadata["height"]
        duration = metadata["duration"]
        attributes = [DocumentAttributeVideo(duration=duration, w=width, h=height, supports_streaming=True)]

        # Upload
        uploader = await fast_upload(output_file, output_file, time.time(), Drone, edit, '**UPLOADING:**')
        await Drone.send_file(
            event.chat_id,
            uploader,
            caption=original_caption,  # Use same caption
            thumb=thumb_path,
            attributes=attributes,
            force_document=False
        )

        await edit.delete()

    except Exception as e:
        print(f"Encoding error: {e}")
        await edit.edit(f"An error occurred.\n\nContact [SUPPORT]({SUPPORT_LINK})", link_preview=False)

    finally:
        await clean_temp_files(temp_files, temp_dir)


async def clean_temp_files(file_list, directory):
    """Clean up all temporary files and directory"""
    try:
        for f in file_list:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(directory):
            shutil.rmtree(directory, ignore_errors=True)
    except Exception as cleanup_error:
        print(f"Cleanup error: {cleanup_error}")
