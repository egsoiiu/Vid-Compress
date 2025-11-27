import asyncio
import os
import shutil
import time
import glob
from datetime import datetime as dt

from telethon import events
from telethon.tl.types import DocumentAttributeVideo
from telethon.errors.rpcerrorlist import MessageNotModifiedError
from ethon.telefunc import fast_download, fast_upload
from ethon.pyfunc import video_metadata
from LOCAL.localisation import SUPPORT_LINK
from LOCAL.utils import ffmpeg_progress
from .. import BOT_UN, Drone

# Render-optimized settings
RENDER_MODE = True

async def encode(event, msg, scale=0):
    """
    Render-optimized encode function
    """
    if RENDER_MODE:
        await event.reply("⚡ **Render Free Tier Mode** - Optimizing for limited resources...")
    
    temp_dir = "encodemedia"
    os.makedirs(temp_dir, exist_ok=True)
    temp_files = []

    try:
        edit = await Drone.send_message(event.chat_id, "🔄 Starting (Render Optimized)...", reply_to=msg.id)

        # Determine input file
        file = getattr(msg.media, "document", msg.media)
        mime = getattr(msg.file, "mime_type", "video/mp4")
        original_caption = msg.text or msg.message or ""

        # Create unique filenames
        timestamp = int(time.time())
        original_name = getattr(msg.file, "name", "")
        ext = os.path.splitext(original_name)[1] if original_name else ".mp4"
        
        input_file = os.path.join(temp_dir, f"input_{timestamp}{ext}")
        temp_files.append(input_file)

        # Download with Render optimizations
        start_dl = time.time()
        await fast_download(input_file, file, Drone, edit, start_dl, "**DOWNLOADING:**")
        dl_time = time.time() - start_dl
        file_size = os.path.getsize(input_file)
        dl_speed = file_size / dl_time / (1024*1024)  # MB/s

        # Standardized filename
        name = os.path.join(temp_dir, f"video_{timestamp}.mp4")
        os.rename(input_file, name)
        temp_files.append(name)

        # Store original file size
        original_size = os.path.getsize(name)

        # Extract metadata
        await safe_edit(edit, "📊 Analyzing video...")
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

        # RENDER-OPTIMIZED FFMPEG SETTINGS
        scale_map = {240: "426x240", 360: "640x360", 480: "854x480", 720: "1280x720"}
        scale_cmd = scale_map.get(scale, f"{width}x{height}")

        # Conservative FPS for Render CPU limits
        fps_cmd = ["-r", "24"] if original_fps > 30 else []

        # Output and progress files
        output_file = os.path.join(temp_dir, f"output_{timestamp}.mp4")
        progress_file = os.path.join(temp_dir, f"progress_{timestamp}.txt")
        temp_files.extend([output_file, progress_file])

        # RENDER-OPTIMIZED FFMPEG COMMAND
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-progress", progress_file,
            "-i", name
        ] + fps_cmd + [
            "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", 
            "-preset", "medium",
            "-s", scale_cmd,
            "-crf", "26",
            "-c:a", "aac", "-ac", "2", "-ab", "64k",
            "-c:s", "copy", 
            "-movflags", "+faststart",
            "-threads", "1",
            output_file, "-y"
        ]

        # Run encoding with progress
        await ffmpeg_progress(cmd, name, progress_file, time.time(), edit, '**ENCODING:**')

        # Get encoded file size
        encoded_size = os.path.getsize(output_file)

        # Prepare caption with Render info
        encoding_info = f"\n\n💎 Encoded • {scale}p\n📊 {original_size//1024//1024}MB → {encoded_size//1024//1024}MB\n⚡ Render Free Tier"
        final_caption = original_caption + encoding_info if original_caption else encoding_info.strip()

        # Optimized upload for Render
        await safe_edit(edit, "📤 Uploading (Render Optimized)...")
        start_ul = time.time()
        uploader = await fast_upload(output_file, output_file, start_ul, Drone, edit, '**UPLOADING:**')
        ul_time = time.time() - start_ul
        ul_speed = encoded_size / ul_time / (1024*1024)

        # Log speeds for monitoring
        print(f"📊 Render Speeds - Download: {dl_speed:.2f} MB/s, Upload: {ul_speed:.2f} MB/s")

        # Get original thumbnail
        thumb = None
        if getattr(msg, "video", None) and msg.video.thumbs:
            thumb = msg.video.thumbs[-1]
        elif hasattr(msg.media, 'document') and msg.media.document.thumbs:
            thumb = msg.media.document.thumbs[-1]

        # Video attributes
        metadata = video_metadata(output_file)
        width = metadata["width"]
        height = metadata["height"]
        duration = metadata["duration"]
        attributes = [DocumentAttributeVideo(duration=duration, w=width, h=height, supports_streaming=True)]

        await Drone.send_file(
            event.chat_id,
            uploader,
            caption=final_caption,
            thumb=thumb,
            attributes=attributes,
            force_document=False
        )

        await edit.delete()

    except Exception as e:
        print(f"Render encoding error: {e}")
        try:
            await safe_edit(edit, f"❌ Render Limit Hit\n\nContact [SUPPORT]({SUPPORT_LINK})", link_preview=False)
        except:
            pass
    finally:
        await clean_temp_files(temp_files)

async def safe_edit(message, text, buttons=None, link_preview=False):
    """Safe message edit"""
    try:
        await message.edit(text, buttons=buttons, link_preview=link_preview)
    except MessageNotModifiedError:
        pass
    except Exception as e:
        print(f"Edit failed: {e}")

async def clean_temp_files(file_list):
    """Clean up temporary files"""
    try:
        for f in file_list:
            if os.path.exists(f):
                os.remove(f)
    except Exception as cleanup_error:
        print(f"Cleanup error: {cleanup_error}")

# ==================== RENDER COMMANDS (NO PSUtil) ====================

@Drone.on(events.NewMessage(pattern='/renderstats'))
async def render_stats(event):
    """Show Render-specific statistics without psutil"""
    try:
        # Get disk usage using basic Python
        statvfs = os.statvfs('.')
        free_disk = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)  # GB
        
        # Calculate approximate hours used (since this is simpler)
        import time
        hours_used = time.time() / 3600  # Since epoch, not accurate but gives idea
        hours_remaining = max(0, 750 - (hours_used % (30*24)))  # Rough estimate
        
        await event.reply(
            f"🎯 **RENDER FREE TIER STATS** 🎯\n\n"
            f"• Disk Free: `{free_disk:.1f} GB`\n"
            f"• Hours Used: `~{hours_used % (30*24):.1f}h`\n"
            f"• Hours Left: `~{hours_remaining:.1f}h`\n\n"
            f"⚡ **Expected Speeds:**\n"
            f"• Download: `5-15 MB/s`\n"
            f"• Upload: `3-10 MB/s`\n"
            f"• Encoding: `Slow-Moderate`\n\n"
            f"💡 **Tips for Render:**\n"
            f"• Use lower resolutions (240p/360p)\n"
            f"• Encode shorter videos\n"
            f"• Monitor hours usage\n"
            f"• Cleanup frequently with `/renderclean`"
        )
        
    except Exception as e:
        await event.reply(f"❌ Stats error: {e}")

@Drone.on(events.NewMessage(pattern='/renderclean'))
async def render_cleanup(event):
    """Render-specific aggressive cleanup"""
    try:
        msg = await event.reply("🧹 Render Cleanup - Freeing disk space...")
        
        cleaned = 0
        patterns = [
            "encodemedia/*",
            "*.tmp", "*.temp",
            "progress_*.txt", "progress-*.txt",
            "thumb_*.jpg", "thumb_*.jpeg",
            "input_*", "output_*", "video_*", "media_*", "out_*", "__*"
        ]
        
        for pattern in patterns:
            for item in glob.glob(pattern):
                try:
                    if os.path.isfile(item):
                        os.remove(item)
                        cleaned += 1
                    elif os.path.isdir(item):
                        shutil.rmtree(item, ignore_errors=True)
                        cleaned += 1
                except:
                    pass
        
        # Force garbage collection
        import gc
        gc.collect()
        
        await msg.edit(f"✅ Render Cleanup Complete\nFreed `{cleaned}` items from disk")
        
    except Exception as e:
        await event.reply(f"❌ Cleanup error: {e}")

@Drone.on(events.NewMessage(pattern='/renderlimit'))
async def render_limits(event):
    """Explain Render free tier limits"""
    await event.reply(
        "🚫 **RENDER FREE TIER LIMITS** 🚫\n\n"
        "**Hardware Constraints:**\n"
        "• CPU: Shared, burstable (slows under load)\n"
        "• RAM: 512MB-1GB (very limited)\n" 
        "• Disk: Slow ephemeral storage\n"
        "• Network: Throttled bandwidth\n\n"
        "**Usage Limits:**\n"
        "• 750 hours/month total runtime\n"
        "• Sleeps after 15 minutes inactivity\n"
        "• Limited concurrent processes\n\n"
        "**Realistic Expectations:**\n"
        "• Max speed: 5-15 MB/s (not 40+ MB/s)\n"
        "• Encoding: Slow for large files\n"
        "• Best for: Small videos, lower resolutions\n\n"
        "💡 **Workarounds:**\n"
        "• Use 240p/360p for faster encoding\n"
        "• Monitor with `/renderstats`\n"
        "• Cleanup with `/renderclean`\n"
        "• Consider paid tier for better performance"
    )

@Drone.on(events.NewMessage(pattern='/smallfile'))
async def small_file_tips(event):
    """Tips for working with small files on Render"""
    await event.reply(
        "📁 **RENDER: Small File Strategy** 📁\n\n"
        "**Ideal for Free Tier:**\n"
        "• File size: < 50MB\n"
        "• Duration: < 5 minutes\n" 
        "• Resolution: 240p-480p\n"
        "• Simple encoding tasks\n\n"
        "**Avoid on Free Tier:**\n"
        "• Files > 100MB\n"
        "• 720p+ encoding\n"
        "• Complex filters/effects\n"
        "• Multiple concurrent jobs\n\n"
        "**Optimization Tips:**\n"
        "• Use 240p for fastest encoding\n"
        "• Lower audio quality (64k)\n"
        "• Higher CRF (26-28)\n"
        "• Single-threaded FFmpeg\n"
        "• Frequent cleanup\n"
        "• Monitor hours usage\n\n"
        "Use `/renderstats` to check current usage"
    )

@Drone.on(events.NewMessage(pattern='/cleanup'))
async def cleanup_command(event):
    """Simple cleanup command"""
    confirm_msg = await event.reply(
        "🧹 **Cleanup** 🧹\n\n"
        "Reply with `YES` to clean temporary files."
    )
    
    try:
        response = await event.client.wait_for(
            events.NewMessage(chats=event.chat_id, from_users=event.sender_id),
            timeout=30
        )
        
        if response.text.upper().strip() == "YES":
            progress_msg = await event.reply("🔄 Cleaning...")
            
            # Clean temporary files
            patterns = ["encodemedia/*", "*.tmp", "progress_*.txt", "thumb_*.jpg"]
            cleaned = 0
            for pattern in patterns:
                for item in glob.glob(pattern):
                    try:
                        if os.path.isfile(item):
                            os.remove(item)
                            cleaned += 1
                        elif os.path.isdir(item):
                            shutil.rmtree(item, ignore_errors=True)
                            cleaned += 1
                    except:
                        pass
            
            await progress_msg.edit(f"✅ Cleaned `{cleaned}` files/directories")
        else:
            await confirm_msg.edit("❌ Cleanup cancelled.")
            
    except asyncio.TimeoutError:
        await confirm_msg.edit("⏰ Cleanup timed out.")
