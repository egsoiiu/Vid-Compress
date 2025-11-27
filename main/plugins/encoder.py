import asyncio
import os
import shutil
import time
from datetime import datetime as dt

from telethon.tl.types import DocumentAttributeVideo
from telethon.errors.rpcerrorlist import MessageNotModifiedError
from ethon.telefunc import fast_download, fast_upload
from ethon.pyfunc import video_metadata
from LOCAL.localisation import SUPPORT_LINK
from LOCAL.utils import ffmpeg_progress
from .. import BOT_UN


async def encode(event, msg, scale=0):
    """
    Encode video to a given scale (240, 360, 480, 720)
    Modified to work with main.py directory structure
    """
    Drone = event.client
    
    # Use the same directory name as main.py expects
    temp_dir = "encodemedia"
    os.makedirs(temp_dir, exist_ok=True)
    temp_files = []

    try:
        # Send initial progress message
        try:
            edit = await Drone.send_message(event.chat_id, "Trying to process.", reply_to=msg.id)
        except Exception as e:
            print(f"Failed to send initial message: {e}")
            return

        # Determine input file
        file = getattr(msg.media, "document", msg.media)
        mime = getattr(msg.file, "mime_type", "video/mp4")
        original_caption = msg.text or msg.message or ""

        # Create unique filenames within the encodemedia directory
        timestamp = int(time.time())
        
        # Determine filename & extension safely
        original_name = getattr(msg.file, "name", "")
        ext = os.path.splitext(original_name)[1] if original_name else ".mp4"
        
        input_file = os.path.join(temp_dir, f"input_{timestamp}{ext}")
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
        await safe_edit(edit, "Extracting metadata...")
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
            return await safe_edit(edit, f"The video is already in {scale}p resolution.")

        # Determine output resolution
        scale_map = {240: "426x240", 360: "640x360", 480: "854x480", 720: "1280x720"}
        scale_cmd = scale_map.get(scale, f"{width}x{height}")

        # FPS only if original >30
        fps_cmd = ["-r", "30"] if original_fps > 30 else []

        # Output and progress files
        output_file = os.path.join(temp_dir, f"output_{timestamp}.mp4")
        progress_file = os.path.join(temp_dir, f"progress_{timestamp}.txt")
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

        # Get encoded file size for comparison
        encoded_size = os.path.getsize(output_file)

        # Prepare caption with encoding info
        encoding_info = f"\n\n💎 Encoded • {scale}p\n📊 {original_size//1024//1024}MB → {encoded_size//1024//1024}MB"
        final_caption = original_caption + encoding_info if original_caption else encoding_info.strip()

        # Get original thumbnail
        thumb = None
        if getattr(msg, "video", None) and msg.video.thumbs:
            thumb = msg.video.thumbs[-1]
        elif hasattr(msg.media, 'document') and msg.media.document.thumbs:
            thumb = msg.media.document.thumbs[-1]

        # Download thumbnail
        thumb_path = None
        if thumb:
            try:
                thumb_path = os.path.join(temp_dir, f"thumb_{timestamp}.jpg")
                # Download thumbnail properly
                thumb_data = await Drone.download_media(msg, file=thumb_path, thumb=-1)
                if thumb_data and os.path.exists(thumb_data):
                    thumb_path = thumb_data
                    temp_files.append(thumb_path)
                else:
                    thumb_path = None
            except Exception as e:
                print(f"Thumbnail download error: {e}")
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
            caption=final_caption,
            thumb=thumb_path,
            attributes=attributes,
            force_document=False
        )

        await edit.delete()

    except Exception as e:
        print(f"Encoding error: {e}")
        try:
            await safe_edit(edit, f"An error occurred.\n\nContact [SUPPORT]({SUPPORT_LINK})", link_preview=False)
        except:
            pass

    finally:
        # Cleanup - but DON'T remove the encodemedia directory itself
        # main.py will handle directory removal after the function completes
        await clean_temp_files(temp_files)


async def safe_edit(message, text, buttons=None, link_preview=False):
    """Safely edit message without throwing MessageNotModifiedError"""
    try:
        await message.edit(text, buttons=buttons, link_preview=link_preview)
    except MessageNotModifiedError:
        # Message already has this content, that's fine
        pass
    except Exception as e:
        print(f"Edit failed: {e}")


async def clean_temp_files(file_list):
    """Clean up temporary files but not the directory"""
    try:
        for f in file_list:
            if os.path.exists(f):
                os.remove(f)
    except Exception as cleanup_error:
        print(f"Cleanup error: {cleanup_error}")
